# app/__init__.py
import os
import logging
import asyncio
from flask import Flask
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from prometheus_client import REGISTRY
from prometheus_flask_exporter import PrometheusMetrics
from .ocp_utils import OCPClient


import yaml
import torch
import requests
from rasa.core.agent import Agent
from rasa.shared.utils.io import json_to_string

# Import your blueprints and utilities
from .routes import api_bp
from .utils import setup_logging, load_faiss_index_and_metadata
from .slack_integration import SlackClient
from .remote_llm_client import RemoteLLMClient


logger = logging.getLogger(__name__)

class NLUModel:

    def __init__(self, model_path: str) -> None:
        if not os.path.exists(model_path):
            logger.error(f"NLU model not found at {model_path}. Please train the model first.")
            raise FileNotFoundError(f"NLU model not found at {model_path}")
        
        # Load the Rasa NLU model using Agent
        self.agent = Agent.load(model_path)
        logger.info("NLU model loaded.")

    async def parse_message(self, message: str) -> dict:
        message = message.strip()
        # Use asyncio to parse the message asynchronously
        result = await self.agent.parse_message(message)
        return result  # Return the result as a dictionary


def fetch_and_set_bot_user_id(app):
    slack_bot_token = app.config['SLACK_CONFIG'].get('slack_bot_token')
    if not slack_bot_token:
        raise ValueError("Slack bot token is missing from the configuration.")

    response = requests.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {slack_bot_token}"}
    )

    if response.status_code == 200:
        bot_info = response.json()
        if bot_info.get('ok'):
            app.config['SLACK_CONFIG']['bot_user_id'] = bot_info.get('user_id')
            logger.info(f"Bot User ID set to: {bot_info.get('user_id')}")
        else:
            error_msg = bot_info.get('error', 'Unknown error')
            raise ValueError(f"Error fetching bot info: {error_msg}")
    else:
        raise ValueError(f"Failed to fetch bot user ID from Slack API. Status code: {response.status_code}")


def create_app(config_path='../config.yaml', registry=None):
    # Load environment variables from .env
    load_dotenv()

    app = Flask(__name__)

    # Load configuration
    config_file_path = os.path.join(os.path.dirname(__file__), config_path)
    if not os.path.exists(config_file_path):
        logger.error(f"Configuration file not found at {config_file_path}")
        raise FileNotFoundError(f"Configuration file not found at {config_file_path}")

    with open(config_file_path, 'r') as f:
        config = yaml.safe_load(f)

    # Application configurations
    app.config['API_CONFIG'] = config.get('api_config', {})
    app.config['SLACK_CONFIG'] = {
        'slack_bot_token': os.getenv('SLACK_BOT_TOKEN', config.get('slack_config', {}).get('slack_bot_token', '')),
        'slack_signing_secret': os.getenv('SLACK_SIGNING_SECRET', config.get('slack_config', {}).get('slack_signing_secret', '')),
        'slack_channel': config.get('slack_config', {}).get('slack_channel', '#netsentenial')
    }
    app.config['TRAINING_CONFIG'] = config.get('training_config', {})
    app.config['RAG_CONFIG'] = config.get('rag_config', {})
    app.config['REMOTE_LLM_CONFIG'] = app.config['RAG_CONFIG'].get('remote_llm', {})
    app.config['OCP_CONFIG'] = {
        'kubeconfig_path': config.get('ocp_config', {}).get('kubeconfig_path', '/path/to/kubeconfig'),
        'auth_method': config.get('ocp_config', {}).get('auth_method', 'kubeconfig'),  # 'kubeconfig' or 'token'
        'prometheus_url': os.getenv('PROMETHEUS_URL', config.get('ocp_config', {}).get('prometheus_url', ''))
    }

    # Setup logging
    log_level = app.config['TRAINING_CONFIG'].get('log_level', 'INFO').upper()
    log_file = os.path.join(os.path.dirname(__file__), '..', 'logs', 'app.log')

    # Ensure the logs directory exists
    logs_dir = os.path.dirname(log_file)
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        logger.info(f"Created logs directory at {logs_dir}")

    setup_logging(log_level, log_file)
    logger.info("Logging is set up.")

    # Initialize Prometheus Metrics
    if registry is None:
        registry = REGISTRY

    metrics = PrometheusMetrics(app, registry=registry)
    metrics.info('app_info', 'NetSentenial Backend API', version='1.0.0')

    # Initialize Rate Limiter
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["240000 per day", "10000 per hour"]
    )
    limiter.init_app(app)

    # Initialize Models and Slack Client
    try:

        # Load the embedding model for RAG
        rag_config = app.config['RAG_CONFIG']
        # llm_model_name = rag_config['llm_model_name']
        # llm_model_type = rag_config.get('llm_model_type', 'seq2seq')
        nlu_model_path = rag_config.get('nlu_model_path', 'rasa/models/nlu-model.tar.gz')  # Default value if not set

        # embedding_model_name = rag_config.get('embedding_model_name', 'all-MiniLM-L6-v2')
        # embedding_model_path = rag_config.get('embedding_model_path', 'models/embedding_models/all-MiniLM-L6-v2')  # Get the path from config

        # from sentence_transformers import SentenceTransformer
        # if not os.path.exists(embedding_model_path):
        #     logger.error(f"Embedding model not found at {embedding_model_path}.")
        #     raise FileNotFoundError(f"Embedding model not found at {embedding_model_path}.")

        # embedding_model = SentenceTransformer(embedding_model_path)
        # logger.info(f"Embedding model '{embedding_model_name}' loaded from {embedding_model_path}.")


        # Load the LLM model for RAG
        # from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM

        # tokenizer = AutoTokenizer.from_pretrained(llm_model_name)
        # # Set pad_token_id and eos_token_id if not set
        # if tokenizer.pad_token_id is None:
        #     tokenizer.pad_token_id = tokenizer.eos_token_id

        # if llm_model_type == 'seq2seq':
        #     llm_model = AutoModelForSeq2SeqLM.from_pretrained(llm_model_name)
        # elif llm_model_type == 'causal':
        #     llm_model = AutoModelForCausalLM.from_pretrained(llm_model_name)
        # else:
        #     raise ValueError(f"Unsupported llm_model_type: {llm_model_type}")

        # # Move model to device (CPU or GPU)
        # device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        # llm_model.to(device)

        # logger.info(f"LLM model '{llm_model_name}' of type '{llm_model_type}' loaded.")


            # Initialize Remote LLM Client
        remote_llm_config = app.config['REMOTE_LLM_CONFIG']
        model_name = remote_llm_config.get('model_name')
        llm_url = remote_llm_config.get('url')
        llm_token = remote_llm_config.get('token')
        verify_ssl = remote_llm_config.get('verify_ssl', True)

        if not llm_url:
            logger.error("Remote LLM URL is not configured.")
            raise ValueError("Remote LLM URL is missing.")

        remote_llm_client = RemoteLLMClient(url=llm_url, model_name=model_name, token=llm_token, verify_ssl=verify_ssl)
        logger.info("Remote LLM client initialized.")


        # Load FAISS index and metadata
        faiss_index_path = rag_config.get('faiss_index_path')
        metadata_store_path = rag_config.get('metadata_store_path')
        faiss_index, metadata_store = load_faiss_index_and_metadata(faiss_index_path, metadata_store_path)
        logger.info("FAISS index and metadata store loaded.")

        # Build event_id_index
        event_id_index = {item['event_id']: item for item in metadata_store}
        logger.info("Event ID index built.")

        # Initialize OCP Client
        ocp_config = app.config['OCP_CONFIG']
        kubeconfig_path = ocp_config.get('kubeconfig_path')
        prometheus_url = ocp_config.get('prometheus_url')

        try:
            ocp_client = OCPClient(kubeconfig_path=kubeconfig_path, prometheus_url=prometheus_url)
        except Exception as ocp_exception:
            logging.error(f"Failed to initialize OCP Client: {ocp_exception}")
            ocp_client = None

        logger.info("OCP client initialized.")

        # Initialize Slack Client
        slack_config = app.config['SLACK_CONFIG']
        slack_bot_token = slack_config.get('slack_bot_token')
        if not slack_bot_token:
            logger.error("Slack bot token is not configured.")
            raise ValueError("Slack bot token is missing.")
        slack_client = SlackClient(slack_bot_token)

        # Fetch and set the bot user ID
        fetch_and_set_bot_user_id(app)

        # Load the NLU model using the new NLUModel class
        nlu_model_full_path = os.path.join(os.path.dirname(__file__), '..', nlu_model_path)
        nlu_interpreter = NLUModel(nlu_model_full_path)

        logger.info("NLU interpreter loaded using Agent.")

        # Attach models and clients to app for access in routes
        app.persistent_state = {
            'remote_llm_client': remote_llm_client,
            'faiss_index': faiss_index,
            'metadata_store': metadata_store,
            'event_id_index': event_id_index,
            'ocp_client': ocp_client,
            'slack_client': slack_client,
            'nlu_interpreter': nlu_interpreter
        }

        logger.info("Models, FAISS index, Slack client, and NLU model initialized.")
        logger.info("Persistent state set with components: %s", list(app.persistent_state.keys()))

    except Exception as e:
        logger.error(f"Failed to initialize models or Slack client: {e}")
        raise e

    # Register Blueprints
    app.register_blueprint(api_bp)

    return app
