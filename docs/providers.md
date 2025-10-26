# ⚙️ providers.json - Complete Documentation

## 🎯 Overview

**File**: `backend/src/core/providers.json`  
**Size**: 3,834 characters (3.8 KB)  
**Purpose**: The **LLM provider registry** that defines all supported AI models and their configurations

This file is VebGen's **model marketplace**—a centralized configuration that lists every supported AI provider (OpenAI, Anthropic, Google, OpenRouter, Hugging Face) and their available models. It's the **single source of truth** for:
- **Provider metadata** (display names, client classes)
- **API configuration** (base URLs, authentication)
- **Model lists** (120+ models across 5 providers)
- **Integration settings** (model prefixes, custom configs)

**Think of it as**: A catalog of all AI models VebGen can work with—from GPT-4 to DeepSeek R1 to Gemini 2.5 Pro—all in one JSON file.

---

## 🧠 For Users: What This File Does

### The Model Selection System

**The Problem**: Supporting multiple AI providers is complex
- Each provider has different API endpoints
- Different authentication methods
- Different model naming conventions
- Different client libraries

**VebGen's Solution**: Single configuration file defines all providers

**What This Enables**:
> ```text
> Settings → AI Model Selection
> ├─ Provider: [OpenAI ▼]
> │  ├─ OpenAI
> │  ├─ Anthropic
> │  ├─ Google
> │  ├─ OpenRouter (120+ models!)
> │  └─ Hugging Face
> │
> └─ Model: [gpt-4o ▼]
>    ├─ gpt-5 (New!)
>    ├─ o3 (Reasoning)
>    ├─ gpt-4o (Recommended)
>    ├─ gpt-4-turbo
>    └─ ... (11 OpenAI models)
> ```

**You change the dropdown → VebGen switches models seamlessly!**

---

### Supported Providers

**5 Major Providers** with **120+ models**:

**1. Google** (5 models)
- Gemini 2.5 Pro (Latest, smartest)
- Gemini 2.5 Flash (Fastest)
- Gemini 1.5 Pro
- Gemini 1.5 Flash
- Gemini 1.0 Pro

**2. OpenAI** (11 models)
- GPT-5 (Latest)
- o3, o4-mini (Reasoning models)
- GPT-4o, GPT-4-turbo (Recommended for coding)
- GPT-4o-mini (Fast, cheap)
- GPT-3.5-turbo (Budget option)

**3. Anthropic** (4 models)
- Claude Opus 4.1 (Latest, smartest)
- Claude Opus 4
- Claude Sonnet 4 (Fast, accurate)
- Claude 3.7 Sonnet (Previous generation)

**4. OpenRouter** (30 models)
- **20 FREE models!** (DeepSeek, Qwen, Llama 3.3, Gemma 3)
- **10 paid models** (Claude Sonnet 4, GPT-5, Gemini 2.5 Pro)
- Access to 200+ models via single API key

**5. Hugging Face** (25 models)
- DeepSeek R1 (Open reasoning model)
- DeepSeek Coder V2 (236B parameters!)
- Qwen 2.5 Coder (Best open-source coder)
- Llama 3.1 70B
- Mixtral 8x22B

---

### How to Add Your Own Provider

**Step 1: Edit `providers.json`**
```json
{
  "mycompany": {
    "display_name": "My Company AI",
    "api_key_name": "MYCOMPANY_API_KEY",
    "client_class": "OpenAIClient", // Reuse existing client
    "client_config": {
      "api_base": "https://api.mycompany.com/v1",
      "model_prefix": ""
    },
    "models": [
      "mymodel-large-v1",
      "mymodel-small-v1"
    ]
  }
}
```

**Step 2: Set API key in VebGen**
> VebGen prompts: "Enter API Key for My Company AI Agent"
> You enter: mycompany_api_key_12345
> VebGen stores securely in OS keyring

**Step 3: Select in UI**
> ```text
> Provider: [My Company AI ▼]
> Model:    [mymodel-large-v1 ▼]
> ```

**That's it!** No code changes needed.

---

### How to Manage Models (The Easy Way - NEW in v0.3.0)

**The Problem**: Manually editing `providers.json` is risky and inconvenient just to add a new model ID (e.g., `gpt-5` is released).

**VebGen's Solution**: A UI-driven model manager.

**How It Works**:
1.  **Select a Provider**: In the VebGen UI, choose a specific provider like "OpenAI" from the dropdown.
2.  **Click "Manage"**: A "Manage" button appears next to the model selection dropdown.
3.  **Add or Remove**: A dialog opens showing all current models for that provider. You can:
    -   Type a new model ID (e.g., `gpt-5-turbo`) and click "Add Model".
    -   Click the "🗑️" icon next to a model to remove it from your list.

**What Happens Behind the Scenes**:
- VebGen calls `config_manager.add_model_to_provider()` or `remove_model_from_provider()`.
- It safely updates `providers.json` for you.
- The model dropdown in the UI instantly refreshes with the new list.

**This is the recommended way to add or remove models for an *existing* provider.** Only edit `providers.json` manually when adding a completely new provider.

---

## �‍💻 For Developers: Technical Architecture

### JSON Schema

```json
{
  "<provider_id>": {
    "display_name": "Human-Readable Name",
    "api_key_name": "SECURE_STORAGE_KEY_NAME",
    "client_class": "PythonClientClassName",
    "client_config": {
      "api_base": "https://api.provider.com/v1",
      "model_prefix": "optional-prefix/"
    },
    "models": [
      "model-name-1",
      "model-name-2"
    ]
  }
}
```

**Field Definitions**:

| Field | Type | Required | Purpose | Example |
|-------|------|----------|---------|---------|
| **`<provider_id>`** | string | ✅ | Unique identifier (lowercase, no spaces) | `"openai"`, `"anthropic"` |
| **`display_name`** | string | ✅ | Human-readable provider name (shown in UI) | `"OpenAI"`, `"Google"` |
| **`api_key_name`** | string | ✅ | Key name for secure storage (ALL_CAPS) | `"OPENAI_API_KEY"` |
| **`client_class`** | string | ✅ | Python class from `agent_manager.py` | `"OpenAIClient"` |
| **`client_config`** | object | ✅ | Client-specific configuration | `{"api_base": "..."}` |
| **`client_config.api_base`** | string | ❌ | API endpoint URL | `"https://api.openai.com/v1"` |
| **`client_config.model_prefix`** | string | ❌ | Prefix to prepend to model names | `"gpt-"` (rarely used) |
| **`models`** | array | ✅ | List of available model IDs | `["gpt-4o", "gpt-4-turbo"]` |

---

### How AgentManager Uses This File

**Step 1: Load Configuration**
```python
# In config_manager.py
class ConfigManager:
    def __init__(self, config_dir_path: Path):
        providers_file = config_dir_path / "providers.json"
        with open(providers_file, 'r') as f:
            self.providers_config = json.load(f)

    # Example result:
    # {
    #   "openai": {
    #     "display_name": "OpenAI",
    #     "api_key_name": "OPENAI_API_KEY",
    #     "client_class": "OpenAIClient",
    #     ...
    #   },
    #   ...
    # }
```

**Step 2: Initialize AgentManager**
```python
# In agent_manager.py
class AgentManager:
    def __init__(self, provider_id: str, model_id: str, config_manager: ConfigManager):
        # Load provider config from JSON
        provider_config = config_manager.providers_config.get(provider_id)
        # provider_config = {
        #   "display_name": "OpenAI",
        #   "api_key_name": "OPENAI_API_KEY",
        #   "client_class": "OpenAIClient",
        #   "client_config": {"api_base": "https://api.openai.com/v1"}
        # }

        # Extract details
        key_name = provider_config["api_key_name"]  # "OPENAI_API_KEY"
        client_class_name = provider_config["client_class"]  # "OpenAIClient"
        client_config = provider_config.get("client_config", {})
        
        # Load API key from secure storage
        api_key = retrieve_credential(key_name)
        
        # Get client class from factory
        ClientClass = self._get_client_class(client_class_name)
        # Returns: OpenAIClient
        
        # Instantiate client
        self.agent = ClientClass(
            model=model_id,  # "gpt-4o"
            api_key=api_key,
            **client_config  # api_base, etc.
        )
```

**Step 3: Make API Call**
> All providers now use same interface!
```python
response = agent_manager.invoke_agent(system_prompt, messages, temperature=0.1)
```

---

### Provider-Specific Details

#### 1. Google Configuration

```json
{
  "google": {
    "display_name": "Google",
    "api_key_name": "GOOGLE_API_KEY",
    "client_class": "GoogleGenAIClient",
    "client_config": {
      "api_base": "", 
      "model_prefix": ""
    },
    "models": [
      "gemini-2.5-pro",
      "gemini-2.5-flash", 
      "gemini-1.5-pro",
      "gemini-1.5-flash",
      "gemini-1.0-pro"
    ]
  }
}
```

**Notes**:
- Uses Google's official `google-generativeai` SDK
- `api_base` empty because SDK handles endpoints
- Free tier: 1,500 requests/day for Gemini 1.5 Flash

---

#### 2. OpenAI Configuration

```json
{
  "openai": {
    "display_name": "OpenAI",
    "api_key_name": "OPENAI_API_KEY",
    "client_class": "OpenAIClient",
    "client_config": {
      "api_base": "https://api.openai.com/v1",
      "model_prefix": ""
    },
    "models": [
      "gpt-5",
      "o3",
      "o4-mini",
      "gpt-4-turbo",
      "gpt-4o",
      "gpt-4",
      "gpt-4o-mini",
      "gpt-4o-pro",
      "o1",
      "gpt-3.5-turbo",
      "gpt-3.5"
    ]
  }
}
```

**Notes**:
- Standard OpenAI API endpoint
- Pricing: $0.60/1M tokens (GPT-4o-mini) → $60/1M tokens (GPT-4)
- 128k context window for most models

---

#### 3. Anthropic Configuration

```json
{
  "anthropic": {
    "display_name": "Anthropic",
    "api_key_name": "ANTHROPIC_API_KEY",
    "client_class": "AnthropicClient",
    "client_config": {
      "api_base": "https://api.anthropic.com/v1",
      "model_prefix": ""
    },
    "models": [
      "claude-opus-4-1-20250805",   
      "claude-opus-4-20250514",     
      "claude-sonnet-4-20250514",  
      "claude-3-7-sonnet-20250219"  
    ]
  }
}
```

**Notes**:
- Date-versioned model names (YYYYMMDD)
- 200k context window (Opus 4)
- Best for complex reasoning and code generation

---

#### 4. OpenRouter Configuration

```json
{
  "openrouter": {
    "display_name": "OpenRouter",
    "api_key_name": "OPENROUTER_API_KEY",
    "client_class": "LlmClient",
    "client_config": {
      "api_base": "https://openrouter.ai/api/v1/chat/completions",
      "model_prefix": ""
    },
    "models": [
      "deepseek/deepseek-r1:free",
      "meta-llama/llama-3.3-70b-instruct:free",
      "anthropic/claude-sonnet-4",
      "openai/gpt-5",
      "google/gemini-2.5-pro"
    ]
  }
}
```

**Notes**:
- Single API key for 200+ models
- `:free` suffix = free models
- Model names include provider prefix (`anthropic/`, `openai/`)
- Requires `site_url` and `site_title` parameters (for rankings)

---

#### 5. Hugging Face Configuration

```json
{
  "huggingface": {
    "display_name": "Hugging Face",
    "api_key_name": "HUGGINGFACE_API_TOKEN",
    "client_class": "HuggingFaceClient",
    "client_config": {},
    "models": [
      "deepseek-ai/DeepSeek-R1",
      "deepseek-ai/DeepSeek-Coder-V2-236B",
      "Qwen/Qwen2.5-Coder-32B-Instruct",
      "meta-llama/Meta-Llama-3.1-70B-Instruct"
    ]
  }
}
```

**Notes**:
- Free for most models (serverless inference)
- Model names follow HuggingFace format: `org/repo-name`
- Token starts with `hf_` prefix
- Rate limits: 100 requests/day (free tier)

---

## 🎓 Advanced Features

### 1. Model Prefix System

**Purpose**: Auto-prepend prefix to all model names

**Example**:
```json
{
  "custom_provider": {
    "model_prefix": "myorg/",
    "models": ["model-v1", "model-v2"]
  }
}
```

**Result**:
> User selects: "model-v1"
> AgentManager sends to API: "myorg/model-v1"

**Why This Matters**: Avoids repetition in model lists

---

### 2. Client Class Mapping

**5 Client Classes** (defined in `agent_manager.py`):

```python
client_classes = {
    "OpenAIClient": OpenAIClient,
    "AnthropicClient": AnthropicClient,
    "GoogleGenAIClient": GoogleGenAIClient,
    "HuggingFaceClient": HuggingFaceClient,
    "LlmClient": LlmClient, # Generic OpenAI-compatible
}
```

**When to Use Each**:
- **OpenAIClient**: OpenAI, Azure OpenAI
- **AnthropicClient**: Anthropic Claude
- **GoogleGenAIClient**: Google Gemini
- **HuggingFaceClient**: Hugging Face models
- **LlmClient**: OpenRouter, Groq, Together AI, Anyscale, any OpenAI-compatible API

---

### 3. Custom API Bases

**Use Case**: Self-hosted models or proxies

**Example**:
```json
{
  "local_llm": {
    "display_name": "Local LLM",
    "api_key_name": "LOCAL_LLM_KEY",
    "client_class": "LlmClient",
    "client_config": {
      "api_base": "http://localhost:8000/v1",
      "model_prefix": ""
    },
    "models": ["llama-3-70b", "mistral-7b"]
  }
}
```

**Use Cases**:
- Local LLaMA server (llama.cpp)
- Ollama
- vLLM
- LM Studio
- LocalAI

---

## 📊 Model Statistics

| Provider | Total Models | Free Models | Paid Models | Note |
|----------|--------------|-------------|-------------|------|
| **Google** | 5 | 5 (generous free tier) | 0 | Free tier: 1,500 req/day |
| **OpenAI** | 11 | 0 | 11 | $0.60 - $60 per 1M tokens |
| **Anthropic** | 4 | 0 | 4 | $3 - $75 per 1M tokens |
| **OpenRouter** | 30+ | 20 | 10 | Access to 200+ total models |
| **Hugging Face** | 25 | 25 (serverless) | 0 | 100 req/day free tier |
| **TOTAL** | **75+** | **50+** | **25+** | Plus 200+ via OpenRouter |

---

## 🧪 Validation

### JSON Schema (Recommended)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "patternProperties": {
    "^[a-z_]+$": {
      "type": "object",
      "required": ["display_name", "api_key_name", "client_class", "models"],
      "properties": {
        "display_name": {"type": "string"},
        "api_key_name": {"type": "string", "pattern": "^[A-Z_]+$"},
        "client_class": {
          "type": "string",
          "enum": ["OpenAIClient", "AnthropicClient", "GoogleGenAIClient", "HuggingFaceClient", "LlmClient"]
        },
        "client_config": {"type": "object"},
        "models": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 1
        }
      }
    }
  }
}
```

---

## 🐛 Common Issues

### Issue 1: "Provider 'xyz' not found in configuration"

**Cause**: Typo in provider ID or missing from JSON

**Solution**: Check spelling matches JSON keys exactly
> ❌ Wrong
> `agent_manager = AgentManager("OpenAI", "gpt-4", ...)`

> ✅ Correct
> `agent_manager = AgentManager("openai", "gpt-4", ...)`

---

### Issue 2: "Client class 'XYZClient' not found"

**Cause**: `client_class` value doesn't match imported class

**Solution**: Use one of the 5 supported client classes
> ❌ Wrong
> `"client_class": "CustomClient"`

> ✅ Correct
> `"client_class": "LlmClient"`

---

### Issue 3: Model not showing in UI dropdown

**Cause**: Model name not in `models` array

**Solution**: Add to appropriate provider's models list
```json
{
  "openai": {
    "models": [
      "gpt-4o",
      "your-new-model"
    ]
  }
}
```

---

## ✅ Best Practices

### For Users

1. **Start with free models** (OpenRouter free tier, Hugging Face)
2. **Test quality before paying** (try multiple models for same prompt)
3. **Use latest models** (top of each provider's list = newest)
4. **Use the "Manage" button** in the UI to add new models as they are released.
4. **OpenRouter for variety** (20 free models to experiment with)

### For Developers

1. **Keep provider IDs lowercase** - `"openai"` not `"OpenAI"`
2. **Use ALL_CAPS for key names** - `"OPENAI_API_KEY"` not `"openai_key"`
3. **Validate JSON** - Use JSON schema validator
4. **Test new providers** - Try all models before adding to production
5. **Document custom configs** - Add comments explaining unusual settings
6. **Sort models by preference** - Best models first in array
7. **Include pricing notes** - Help users choose cost-effective models
8. **Update regularly** - New models released monthly

---

## 🌟 Summary

**providers.json** is VebGen's **LLM provider registry**:

✅ **5 major providers** (Google, OpenAI, Anthropic, OpenRouter, Hugging Face)  
✅ **120+ models** (50+ free models available)  
✅ **Single source of truth** (centralized configuration)  
✅ **Hot-swappable** (change models without restart)  
✅ **Extensible** (add providers without code changes)  
✅ **Client agnostic** (5 client classes cover all APIs)  
✅ **Zero hardcoding** (all settings in JSON)  
✅ **Version controlled** (easy to track model additions)  
✅ **User-friendly** (display names shown in UI)  
✅ **Developer-friendly** (simple JSON schema)  

**This is why VebGen can support any LLM provider—just add a JSON entry and go!**

---

<div align="center">

**Want to add a provider?** Just edit this JSON file!

**Questions?** Check agent_manager.md or config_manager.py

</div>