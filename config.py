#!/usr/bin/env python3
"""
Configuration module for OpenRouter API Proxy.
Loads settings from a YAML file and initializes logging.
"""

import logging
import sys
from typing import Dict, Any

import yaml

from constants import CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Configuration file {CONFIG_FILE} not found. "
              "Please create it based on config.yml.example.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing configuration file: {e}")
        sys.exit(1)


def setup_logging(config_: Dict[str, Any]) -> logging.Logger:
    """Configure logging based on configuration."""
    log_level_str = config_.get("server", {}).get("log_level", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger_ = logging.getLogger("openrouter-proxy")
    logger_.info("Logging level set to %s", log_level_str)

    return logger_


def normalize_and_validate_config(config_data: Dict[str, Any]):
    """
    Normalizes the configuration by adding defaults for missing keys
    and validates the structure and types, logging warnings/errors.
    Modifies the config_data dictionary in place.
    """
    # --- OpenRouter Section ---
    # ---- Vane Integration Section ---
    if not isinstance(config_data.get("vane"), dict):
        logger.warning("'vane' section missing or invalid in config.yml. Using defaults.")
        config_data["vane"] = {}
    vane_config = config_data["vane"]
    
    # Default Vane settings
    default_local_model = "openrouter"
    if not isinstance(vane_config.get("local_model_name"), str):
        logger.warning("'vane.local_model_name' missing or invalid. Using default: %s", default_local_model)
        vane_config["local_model_name"] = default_local_model
    
    default_local_token = "openrouter"
    if not isinstance(vane_config.get("local_bearer_token"), str):
        logger.warning("'vane.local_bearer_token' missing or invalid. Using default: %s", default_local_token)
        vane_config["local_bearer_token"] = default_local_token
    
    default_free_models = [
        "google/gemma-3-1b-it:free",
        "meta-llama/llama-3.2-1b-instruct:free",
        "qwen/qwen-2.5-7b-instruct:free"
    ]
    if not isinstance(vane_config.get("free_models"), list) or not vane_config["free_models"]:
        logger.warning("'vane.free_models' missing or invalid. Using defaults: %s", default_free_models)
        vane_config["free_models"] = default_free_models
    else:
        # Validate each model ID is a non-empty string
        validated_models = []
        for i, model in enumerate(vane_config["free_models"]):
            if isinstance(model, str) and model.strip():
                validated_models.append(model.strip())
            else:
                logger.warning("Invalid model at index %d in 'vane.free_models': %s. Skipping.", i, model)
        if not validated_models:
            logger.error("No valid models in 'vane.free_models'. Using defaults.")
            vane_config["free_models"] = default_free_models
        else:
            vane_config["free_models"] = validated_models
    
    default_model_selection = "round-robin"
    if vane_config.get("model_selection") not in ["round-robin", "random"]:
        logger.warning("'vane.model_selection' invalid. Using default: %s", default_model_selection)
        vane_config["model_selection"] = default_model_selection
    
    if not isinstance(vane_config.get("enable_streaming"), bool):
        logger.warning("'vane.enable_streaming' missing or invalid. Using default: True")
        vane_config["enable_streaming"] = True    

    if not isinstance(config_data.get("openrouter"), dict):
        logger.warning("'openrouter' section missing or invalid in config.yml. Using defaults.")
        config_data["openrouter"] = {}
    openrouter_config = config_data["openrouter"]

    default_base_url = "https://openrouter.ai/api/v1"
    if not isinstance(openrouter_config.get("base_url"), str):
        logger.warning(
            "'openrouter.base_url' missing or invalid in config.yml. Using default: %s",
            default_base_url
        )
        openrouter_config["base_url"] = default_base_url
    # Remove trailing slash if present
    openrouter_config["base_url"] = openrouter_config["base_url"].rstrip("/")

    default_public_endpoints = ["/api/v1/models"]
    if "public_endpoints" in openrouter_config and openrouter_config["public_endpoints"] is None:
        openrouter_config["public_endpoints"] = []
    if not isinstance(openrouter_config["public_endpoints"], list):
        logger.warning(
            "'openrouter.public_endpoints' missing or invalid in config.yml. "
            "Using default: %s",
            default_public_endpoints
        )
        openrouter_config["public_endpoints"] = default_public_endpoints
    else:
        validated_endpoints = []
        for i, endpoint in enumerate(openrouter_config["public_endpoints"]):
            if not isinstance(endpoint, str):
                logger.warning("Item %d in 'openrouter.public_endpoints' is not a string. Skipping.", i)
                continue
            if not endpoint:
                logger.warning("Item %d in 'openrouter.public_endpoints' is empty. Skipping.", i)
                continue
            # Ensure leading slash
            if not endpoint.startswith("/"):
                validated_endpoints.append("/" + endpoint)
            else:
                validated_endpoints.append(endpoint)
        openrouter_config["public_endpoints"] = validated_endpoints

    if not isinstance(openrouter_config.get("keys"), list):
        logger.warning("'openrouter.keys' missing or invalid in config.yml. Using empty list.")
        openrouter_config["keys"] = []
    if not openrouter_config["keys"]:
        logger.warning(
            "'openrouter.keys' list is empty in config.yml. "
            "Proxy will not work for authenticated endpoints."
        )

    def_key_selection_strategy = "round-robin"
    if (not isinstance(key_selection_strategy := openrouter_config.get("key_selection_strategy"), str) or
            key_selection_strategy not in ["round-robin", "first", "random"]):
        logger.warning(
            "'openrouter.key_selection_strategy' is unknown: '%s', set '%s'",
            str(key_selection_strategy), def_key_selection_strategy
        )
        openrouter_config["key_selection_strategy"] = def_key_selection_strategy

    if not isinstance(openrouter_config.get("key_selection_opts"), list):
        logger.warning("'openrouter.key_selection_opts' missing or invalid in config.yml. Using empty list.")
        openrouter_config["key_selection_opts"] = []

    default_free_only = False
    if not isinstance(openrouter_config.get("free_only"), bool):
         logger.warning(
             "'openrouter.free_only' missing or invalid in config.yml. Using default: %s",
             default_free_only
         )
         openrouter_config["free_only"] = default_free_only

    default_global_rate_delay = 0
    if not isinstance(openrouter_config.get("global_rate_delay"), (int, float)):
         logger.warning(
             "'openrouter.global_rate_delay' missing or invalid in config.yml. "
             "Using default: %s",
             default_global_rate_delay
         )
         openrouter_config["global_rate_delay"] = default_global_rate_delay

    # --- Request Proxy Section ---
    if not isinstance(config_data.get("requestProxy"), dict):
        logger.warning("'requestProxy' section missing or invalid in config.yml. Using defaults.")
        config_data["requestProxy"] = {}
    proxy_config = config_data["requestProxy"]

    default_proxy_enabled = False
    if not isinstance(proxy_config.get("enabled"), bool):
        logger.warning(
            "'requestProxy.enabled' missing or invalid in config.yml. Using default: %s",
            default_proxy_enabled
        )
        proxy_config["enabled"] = default_proxy_enabled

    default_proxy_url = ""
    if not isinstance(proxy_config.get("url"), str):
        logger.warning(
            "'requestProxy.url' missing or invalid in config.yml. Using default: '%s'",
            default_proxy_url
        )
        proxy_config["url"] = default_proxy_url


# Load configuration
config = load_config()

# Initialize logging
logger = setup_logging(config)

# Normalize and validate configuration (modifies config in place)
normalize_and_validate_config(config)
