from esperanto import LanguageModel
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger

from open_notebook.ai.models import LocalCLIModelHandle, model_manager
from open_notebook.audit.recorder import AuditCallbackHandler
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import token_count


async def provision_langchain_model(
    content, model_id, default_type, **kwargs
) -> BaseChatModel:
    """
    Returns the best model to use based on the context size and on whether there is a specific model being requested in Config.
    If context > 105_000, returns the large_context_model
    If model_id is specified in Config, returns that model
    Otherwise, returns the default model for the given type
    """
    tokens = token_count(content)
    model = None
    selection_reason = ""

    if tokens > 105_000:
        selection_reason = f"large_context (content has {tokens} tokens)"
        logger.debug(
            f"Using large context model because the content has {tokens} tokens"
        )
        model = await model_manager.get_default_model("large_context", **kwargs)
    elif model_id:
        selection_reason = f"explicit model_id={model_id}"
        model = await model_manager.get_model(model_id, **kwargs)
    else:
        selection_reason = f"default for type={default_type}"
        model = await model_manager.get_default_model(default_type, **kwargs)

    logger.debug(f"Using model: {model}")

    if model is None:
        logger.error(
            f"Model provisioning failed: No model found. "
            f"Selection reason: {selection_reason}. "
            f"model_id={model_id}, default_type={default_type}. "
            f"Please check Manage → Models and ensure a default model is configured for '{default_type}'."
        )
        raise ConfigurationError(
            f"No model configured for {selection_reason}. "
            f"Please go to Manage → Models and configure a default model for '{default_type}'."
        )

    if isinstance(model, LocalCLIModelHandle):
        lc_model = model.to_langchain()
        _attach_audit(
            lc_model, model.provider, model.model_name, model.model_id, default_type
        )
        return lc_model

    if not isinstance(model, LanguageModel):
        logger.error(
            f"Model type mismatch: Expected LanguageModel but got {type(model).__name__}. "
            f"Selection reason: {selection_reason}. "
            f"model_id={model_id}, default_type={default_type}."
        )
        raise ConfigurationError(
            f"Model is not a LanguageModel: {model}. "
            f"Please check that the model configured for '{default_type}' is a language model, not an embedding or speech model."
        )

    lc_model = model.to_langchain()
    _attach_audit(
        lc_model,
        str(getattr(model, "provider", "unknown")),
        str(getattr(model, "model_name", "unknown")),
        model_id,
        default_type,
    )
    return lc_model


def _attach_audit(
    lc_model: BaseChatModel,
    provider: str,
    model_name: str,
    model_id: str | None,
    feature: str,
) -> None:
    """Record every call of this model instance in the AI audit log."""
    try:
        handler = AuditCallbackHandler(provider, model_name, model_id, feature)
        existing = (
            list(lc_model.callbacks or [])
            if isinstance(lc_model.callbacks, list)
            else []
        )
        lc_model.callbacks = existing + [handler]
    except Exception as e:  # auditing must never break a chat
        logger.warning(f"Could not attach audit handler: {e}")
