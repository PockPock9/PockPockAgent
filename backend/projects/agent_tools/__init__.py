"""Compatibility facade for the modular PockPock AI agent tool package.

New capability implementations belong in their focused module; callers may
continue importing the established public functions from this package.
"""

from .common import *
from .artifacts import (
    create_office_artifact, generate_local_image, image_backend_status,
    save_text_artifact,
)
from .research import (
    explicit_task_hosts, is_bulk_media_download_request, normalize_public_url,
    requested_artifact_extension, search_public_site, scrape_public_page,
    website_ssl_context, _PageTextParser, _validate_public_url,
)
from .registry import (
    agent_tool_specs, execute_agent_tool, execute_project_tool,
    project_agent_tool_specs, registered_tool_contracts, registered_tool_specs,
)
from .workspace import (
    apply_project_patch, list_project_files, propose_project_addition, propose_project_edit,
    propose_project_patch, read_project_file, revert_project_addition, search_project, validate_project,
    validate_project_service, task_output_dir, task_output_root,
)
from .contracts import (
    ERROR_CONTRACT_VERSION, TOOL_CONTRACT_VERSION, ToolContract,
    ToolContractError, ToolError, tool_names_for_task_capabilities,
    validate_tool_input, validate_tool_output,
)
from .research_contracts import (
    RESEARCH_CONTRACT_VERSION, ResearchProviderError, ResearchResponse,
    SourceEvidence, SourceRecord, canonical_source_url, deduplicate_sources,
    make_source_record, named_host_page_record, source_identity,
)
from .research_answers import (
    ResearchAnswer, ResearchAnswerValidationError, render_research_answer,
    research_answer_json_schema, validate_research_answer,
)
from .research_exports import (
    SUPPORTED_RESEARCH_EXPORTS, create_research_export,
)
