import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Initialize Jinja2 environment
env = Environment(
    loader=FileSystemLoader(os.path.dirname(__file__)),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_prompt_template(prompt_name: str, state_vars: dict) -> str:
    """
    Load and return a prompt template using Jinja2.

    Args:
        prompt_name: Name of the prompt template file (without .md extension)

        state_vars: Input dict for template render

    Returns:
        The template string with proper variable substitution syntax
    """

    state_vars["CURRENT_TIME"] = datetime.now().strftime("%a %b %d %Y %H:%M:%S %z")

    try:
        template = env.get_template(f"{prompt_name}.md")
        return template.render(**state_vars)
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name}: {e}")
