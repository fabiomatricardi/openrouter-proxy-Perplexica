#!/usr/bin/env python3
"""
Model selector module for Vane integration.
Implements round-robin selection from a list of free OpenRouter models.
"""

import asyncio
from typing import List, Optional

from config import logger

class ModelSelector:
    """Manages selection of free OpenRouter models using round-robin strategy."""
    
    def __init__(self, models: List[str], strategy: str = "round-robin"):
        """
        Initialize the model selector.
        
        Args:
            models: List of model IDs to select from
            strategy: Selection strategy ("round-robin" or "random")
        """
        if not models:
            logger.error("No free models provided for Vane integration.")
            raise ValueError("At least one free model must be configured")
        
        self.models = models
        self.strategy = strategy
        self.current_index = 0
        self.lock = asyncio.Lock()
        logger.info(f"ModelSelector initialized with {len(models)} models: {models}")
    
    async def get_next_model(self, exclude: Optional[List[str]] = None) -> str:
        """
        Get the next available model using the configured strategy.
        
        Args:
            exclude: Optional list of model IDs to exclude (e.g., unavailable models)
            
        Returns:
            Selected model ID
        """
        async with self.lock:
            # Filter out excluded models
            available_models = [m for m in self.models if m not in (exclude or [])]
            
            if not available_models:
                logger.error("No available models after exclusions: %s", exclude)
                # Fallback: return first model even if excluded
                return self.models[0]
            
            if self.strategy == "random":
                import random
                selected = random.choice(available_models)
            else:  # round-robin (default)
                # Find next available model in round-robin order
                attempts = 0
                while attempts < len(self.models):
                    candidate = self.models[self.current_index]
                    self.current_index = (self.current_index + 1) % len(self.models)
                    if candidate in available_models:
                        selected = candidate
                        break
                    attempts += 1
                else:
                    # Fallback if round-robin fails
                    selected = available_models[0]
            
            logger.debug(f"Selected model: {selected}")
            return selected
    
    def get_all_models(self) -> List[str]:
        """Return the full list of configured models."""
        return self.models.copy()