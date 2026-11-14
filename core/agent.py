"""Agent core orchestrator coordinating AI provider, planner, executor, tools, tasks, and memory."""

from __future__ import annotations

import contextlib
from typing import Any

from ai.base import BaseAIProvider
from ai.manager import ProviderManager
from config import Settings, get_settings
from core.approval import ApprovalManager
from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor, ExecutionOutcome
from core.permissions import (
    BasePermissionManager,
    PermissionCategory,
    StrictDefaultDenyPermissionManager,
)
from core.planner import AgentPlanner, Plan
from core.state_machine import AgentState, AgentStateMachine
from core.task_manager import TaskManager
from core.tool_proposal import ToolProposal
from core.tool_registry import ToolRegistry
from infrastructure.logging import get_logger
from memory.base import BaseMemoryStore, ConversationMessage, MessageRole, MessageStatus
from memory.database import SQLiteMemoryStore
from memory.manager import MemoryManager
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from tools.base import BaseTool
from tools.coding_agent import (
    CodingAgentDelegateTaskTool,
    CodingAgentGetTaskStatusTool,
    CodingAgentStatusTool,
    CodingAgentVerifyTaskTool,
)
from tools.filesystem import (
    DirectoryListTool,
    FileArchiveCreateTool,
    FileArchiveExtractTool,
    FileArchiveInspectTool,
    FileCompareDiffTool,
    FileCopyTool,
    FileDeleteTool,
    FileDocumentExtractTool,
    FileEditTextTool,
    FileFindDuplicatesTool,
    FileMetadataTool,
    FileMoveTool,
    FileReadTextTool,
    FileSearchTextTool,
    FileWriteTextTool,
    get_path_security_service,
)
from tools.mock_tools import (
    MockCalculatorTool,
    MockDangerousSystemTool,
    MockSearchTool,
    MockWeatherTool,
)
from tools.system import (
    SystemCPUInfoTool,
    SystemDiskInfoTool,
    SystemMemoryInfoTool,
    SystemNetworkInfoTool,
    SystemOverviewTool,
)
from tools.terminal import (
    TerminalExecuteCommandTool,
    TerminalListCommandsTool,
)
from tools.windows import (
    WindowsAppCloseTool,
    WindowsAppLaunchTool,
    WindowsAppListTool,
    WindowsAudioGetStatusTool,
    WindowsAudioSetMuteTool,
    WindowsAudioSetVolumeTool,
    WindowsDisplayGetBrightnessTool,
    WindowsDisplaySetBrightnessTool,
    WindowsPowerGetStatusTool,
    WindowsPowerLockTool,
    WindowsPowerRestartTool,
    WindowsPowerShutdownTool,
    WindowsPowerSleepTool,
    WindowsWindowCloseTool,
    WindowsWindowFocusTool,
    WindowsWindowListTool,
    WindowsWindowMaximizeTool,
    WindowsWindowMinimizeTool,
    WindowsWindowRestoreTool,
)

logger = get_logger("agent")


class JARVISAgent:
    """Core JARVIS agent orchestrator for multi-provider chat and autonomous planning."""

    def __init__(
        self,
        settings: Settings | None = None,
        ai_provider: BaseAIProvider | None = None,
        permission_manager: BasePermissionManager | None = None,
        memory_store: BaseMemoryStore | None = None,
        memory_manager: MemoryManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.event_bus = event_bus or EventBus()
        allowed_categories = {
            PermissionCategory.READ_ONLY,
            PermissionCategory.COMPUTATION,
            PermissionCategory.SYSTEM_INFO,
            PermissionCategory.NETWORK_INSPECT,
            PermissionCategory.FILE_READ,
            PermissionCategory.FILE_SEARCH,
        }
        if getattr(self.settings, "windows_control_enabled", True):
            allowed_categories.update(
                {
                    PermissionCategory.WINDOWS_APP_READ,
                    PermissionCategory.WINDOWS_WINDOW_READ,
                    PermissionCategory.WINDOWS_WINDOW_CONTROL,
                    PermissionCategory.WINDOWS_AUDIO_READ,
                    PermissionCategory.WINDOWS_DISPLAY_READ,
                    PermissionCategory.WINDOWS_DISPLAY_CONTROL,
                    PermissionCategory.WINDOWS_POWER_READ,
                }
            )
            if getattr(self.settings, "windows_audio_control_enabled", True):
                allowed_categories.add(PermissionCategory.WINDOWS_AUDIO_CONTROL)
            if getattr(self.settings, "windows_app_launch_enabled", True):
                allowed_categories.add(PermissionCategory.WINDOWS_APP_LAUNCH)
            if getattr(self.settings, "windows_app_close_enabled", True):
                allowed_categories.add(PermissionCategory.WINDOWS_APP_CLOSE)
            if getattr(self.settings, "windows_power_control_enabled", True):
                allowed_categories.add(PermissionCategory.WINDOWS_POWER_CONTROL)

            # Phase 7 Browser Agent Permissions
            if getattr(self.settings, "browser_enabled", True):
                allowed_categories.update(
                    {
                        PermissionCategory.BROWSER_NAVIGATE,
                        PermissionCategory.BROWSER_READ,
                        PermissionCategory.BROWSER_TAB,
                        PermissionCategory.BROWSER_SCREENSHOT,
                        PermissionCategory.BROWSER_INTERACT,
                    }
                )

        # Phase 8 File System Modification & Archive Permissions
        if getattr(self.settings, "file_modification_enabled", True):
            allowed_categories.update(
                {
                    PermissionCategory.FILE_WRITE,
                    PermissionCategory.FILE_DELETE,
                    PermissionCategory.FILE_ARCHIVE,
                }
            )

        # Phase 8 Restricted Terminal Execution Permissions
        if getattr(self.settings, "terminal_enabled", True):
            allowed_categories.add(PermissionCategory.TERMINAL_EXECUTE)

        # Phase 8 Antigravity Coding Agent Permissions
        if getattr(self.settings, "antigravity_enabled", True):
            allowed_categories.update(
                {
                    PermissionCategory.CODING_AGENT_DELEGATE,
                    PermissionCategory.CODING_AGENT_VERIFY,
                }
            )

        self.permission_manager = permission_manager or StrictDefaultDenyPermissionManager(
            allowed_categories=allowed_categories
        )
        self.tool_registry = ToolRegistry(
            permission_manager=self.permission_manager,
            event_bus=self.event_bus,
        )
        self.task_manager = TaskManager(event_bus=self.event_bus)
        self.ai_provider = ai_provider or ProviderManager(settings=self.settings)
        self.memory_store = memory_store or SQLiteMemoryStore()
        self.memory_manager = memory_manager or MemoryManager(settings=self.settings)
        self.path_security = get_path_security_service()

        self._current_context = ExecutionContext()
        self._active_session_id: str = self._current_context.session_id

        # Phase 3 Deterministic State Machine
        self.state_machine = AgentStateMachine(
            initial_state=AgentState.IDLE,
            session_id=self._active_session_id,
            event_bus=self.event_bus,
        )

        # Phase 3 Human Approval Manager
        self.approval_manager = ApprovalManager(
            event_bus=self.event_bus,
            permission_manager=self.permission_manager,
        )

        # Phase 3 Planner & Executor Subsystems
        self.planner = AgentPlanner(
            provider_manager=self.ai_provider,
            settings=self.settings,
            event_bus=self.event_bus,
        )
        self.executor = AgentExecutor(
            tool_registry=self.tool_registry,
            provider_manager=self.ai_provider,
            planner=self.planner,
            state_machine=self.state_machine,
            permission_manager=self.permission_manager,
            approval_manager=self.approval_manager,
            settings=self.settings,
            event_bus=self.event_bus,
        )

        # Register standard simulated mock tools and Phase 4 real tools
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register deterministic mock tools and Phase 4 Windows system/file inspection tools."""
        # 1. Phase 3 Deterministic Mocks
        default_tools: list[BaseTool] = [
            MockSearchTool(),
            MockCalculatorTool(),
            MockWeatherTool(),
            MockDangerousSystemTool(),
        ]

        # 2. Phase 4 Real Windows System Intelligence Tools
        if self.settings.system_inspection_enabled:
            default_tools.extend(
                [
                    SystemCPUInfoTool(),
                    SystemMemoryInfoTool(),
                    SystemDiskInfoTool(),
                    SystemNetworkInfoTool(),
                    SystemOverviewTool(),
                ]
            )

        # 3. Phase 4 Real Secure File Reading Tools
        if self.settings.file_reading_enabled:
            default_tools.extend(
                [
                    DirectoryListTool(),
                    FileMetadataTool(),
                    FileReadTextTool(),
                    FileSearchTextTool(),
                ]
            )

        # 4. Phase 6 Real Windows Control & Native Desktop Actions
        if getattr(self.settings, "windows_control_enabled", True):
            windows_tools: list[BaseTool] = []
            # Applications
            windows_tools.append(WindowsAppListTool())
            if getattr(self.settings, "windows_app_launch_enabled", True):
                windows_tools.append(WindowsAppLaunchTool())
            if getattr(self.settings, "windows_app_close_enabled", True):
                windows_tools.append(WindowsAppCloseTool())

            # Windows
            if getattr(self.settings, "windows_window_control_enabled", True):
                windows_tools.extend(
                    [
                        WindowsWindowListTool(),
                        WindowsWindowFocusTool(),
                        WindowsWindowMinimizeTool(),
                        WindowsWindowMaximizeTool(),
                        WindowsWindowRestoreTool(),
                        WindowsWindowCloseTool(),
                    ]
                )

            # Audio
            if getattr(self.settings, "windows_audio_control_enabled", True):
                windows_tools.extend(
                    [
                        WindowsAudioGetStatusTool(),
                        WindowsAudioSetVolumeTool(),
                        WindowsAudioSetMuteTool(),
                    ]
                )

            # Display
            if getattr(self.settings, "windows_display_control_enabled", True):
                windows_tools.extend(
                    [
                        WindowsDisplayGetBrightnessTool(),
                        WindowsDisplaySetBrightnessTool(),
                    ]
                )

            # Power
            if getattr(self.settings, "windows_power_control_enabled", True):
                windows_tools.extend(
                    [
                        WindowsPowerGetStatusTool(),
                        WindowsPowerLockTool(),
                        WindowsPowerSleepTool(),
                        WindowsPowerRestartTool(),
                        WindowsPowerShutdownTool(),
                    ]
                )

            default_tools.extend(windows_tools)

        # 5. Phase 7 Real Browser Agent Tools
        self.browser_service: Any = None
        if getattr(self.settings, "browser_enabled", True):
            try:
                from tools.browser.browser_service import BrowserService
                from tools.browser.browser_tools import (
                    BrowserClickElementTool,
                    BrowserFillFieldTool,
                    BrowserGetHeadingsTool,
                    BrowserGetLinksTool,
                    BrowserGetPageContentTool,
                    BrowserGoBackTool,
                    BrowserGoForwardTool,
                    BrowserNavigateTool,
                    BrowserReloadTool,
                    BrowserScreenshotTool,
                    BrowserScrollTool,
                    BrowserSearchTool,
                    BrowserTabCloseTool,
                    BrowserTabListTool,
                    BrowserTabNewTool,
                    BrowserTabSwitchTool,
                )

                self.browser_service = BrowserService(settings=self.settings)
                browser_tools: list[BaseTool] = [
                    BrowserNavigateTool(self.browser_service),
                    BrowserSearchTool(self.browser_service),
                    BrowserGetPageContentTool(self.browser_service),
                    BrowserGetHeadingsTool(self.browser_service),
                    BrowserGetLinksTool(self.browser_service),
                    BrowserClickElementTool(self.browser_service),
                    BrowserScrollTool(self.browser_service),
                    BrowserFillFieldTool(self.browser_service),
                    BrowserScreenshotTool(self.browser_service),
                    BrowserTabNewTool(self.browser_service),
                    BrowserTabListTool(self.browser_service),
                    BrowserTabSwitchTool(self.browser_service),
                    BrowserTabCloseTool(self.browser_service),
                    BrowserGoBackTool(self.browser_service),
                    BrowserGoForwardTool(self.browser_service),
                    BrowserReloadTool(self.browser_service),
                ]
                default_tools.extend(browser_tools)
                logger.info("Registered 16 Phase 7 Browser Agent tools.")
            except Exception as b_exc:
                logger.warning(f"Failed to initialize Browser Agent tools: {b_exc}")

        # 6. Phase 8 File System Modification & Document Extraction Tools
        if self.settings.file_reading_enabled:
            default_tools.append(FileDocumentExtractTool())
            default_tools.append(FileCompareDiffTool())
            default_tools.append(FileFindDuplicatesTool())

        if getattr(self.settings, "file_modification_enabled", True):
            default_tools.extend(
                [
                    FileWriteTextTool(),
                    FileEditTextTool(),
                    FileCopyTool(),
                    FileMoveTool(),
                    FileDeleteTool(),
                    FileArchiveCreateTool(),
                    FileArchiveInspectTool(),
                    FileArchiveExtractTool(),
                ]
            )

        # 7. Phase 8 Restricted Terminal Agent Tools
        if getattr(self.settings, "terminal_enabled", True):
            default_tools.extend(
                [
                    TerminalExecuteCommandTool(),
                    TerminalListCommandsTool(),
                ]
            )

        # 8. Phase 8 Antigravity Coding Agent Tools
        if getattr(self.settings, "antigravity_enabled", True):
            default_tools.extend(
                [
                    CodingAgentStatusTool(),
                    CodingAgentDelegateTaskTool(),
                    CodingAgentGetTaskStatusTool(),
                    CodingAgentVerifyTaskTool(),
                ]
            )

        for tool in default_tools:
            with contextlib.suppress(Exception):
                self.tool_registry.register(tool)

    @property
    def state(self) -> AgentState:
        """Return the current agent state."""
        return self.state_machine.current_state

    @property
    def active_session_id(self) -> str:
        """Return the ID of the currently active conversation session."""
        return self._active_session_id

    def set_active_session_id(self, session_id: str) -> None:
        """Switch the active session."""
        self._active_session_id = session_id
        self._current_context.session_id = session_id
        self.state_machine.session_id = session_id

    def authorize_cloud_transmission(
        self,
        session_id: str,
        destination_provider: str,
        content_fingerprint: str,
        proposal_id: str = "",
        source_file: str = "",
        character_count: int = 0,
        operation_id: str = "",
    ) -> Any:
        """Authorize single-use transmission of specific local file content to an external provider."""
        import uuid

        prop_id = proposal_id or str(uuid.uuid4())
        return self.executor.authorize_cloud_transmission(
            proposal_id=prop_id,
            session_id=session_id,
            destination_provider=destination_provider,
            content_fingerprint=content_fingerprint,
            source_file=source_file,
            character_count=character_count,
            operation_id=operation_id,
        )

    def revoke_cloud_transmission(
        self,
        proposal_id: str,
        destination_provider: str | None = None,
        content_fingerprint: str | None = None,
    ) -> bool:
        """Revoke authorization to transmit specific local content to an external provider."""
        return self.executor.revoke_cloud_transmission(
            proposal_id=proposal_id,
            destination_provider=destination_provider,
            content_fingerprint=content_fingerprint,
        )

    def create_new_session(self, title: str = "New Conversation") -> str:
        """Create a fresh conversation session."""
        new_id = self.memory_store.create_session(title=title)
        self.set_active_session_id(new_id)
        logger.info(f"Created and switched to new session: {new_id}")
        return new_id

    def clear_active_session(self) -> None:
        """Clear all messages from the current conversation session."""
        self.memory_store.clear_session_messages(self._active_session_id)
        logger.info(f"Cleared messages for session: {self._active_session_id}")

    def set_state(self, state: AgentState, reason: str = "") -> None:
        """Update the agent state via the deterministic state machine."""
        if self.state_machine.can_transition(state):
            self.state_machine.transition_to(state, reason=reason)
        else:
            # Fallback for states not directly in transition graph
            logger.debug(f"Direct set_state fallback: {state.value} ({reason})")

    def initialize(self) -> None:
        """Initialize core agent subsystems and dependencies."""
        logger.info("Initializing JARVIS agent core subsystems...")
        try:
            self.memory_store.initialize()
            self.memory_manager.initialize()
            if self.state_machine.current_state != AgentState.IDLE:
                self.state_machine.reset(new_session_id=self._active_session_id)
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.AGENT_INITIALIZED,
                    payload={
                        "app_name": self.settings.app_name,
                        "version": self.settings.app_version,
                    },
                )
            )
        except Exception as exc:
            self.state_machine.transition_to(
                AgentState.FAILED, reason=f"Initialization failed: {exc}"
            )
            logger.exception("Agent initialization encountered an error.")
            raise

    def get_session_history(self, session_id: str | None = None) -> list[ConversationMessage]:
        """Retrieve recent conversation history for multi-turn context."""
        sid = session_id or self._active_session_id
        return self.memory_store.get_messages(
            session_id=sid,
            limit=self.settings.conversation_history_limit,
        )

    def record_user_message(self, text: str, session_id: str | None = None) -> ConversationMessage:
        """Persist user message and emit events."""
        sid = session_id or self._active_session_id
        msg = ConversationMessage(
            role=MessageRole.USER,
            content=text,
            session_id=sid,
            status=MessageStatus.COMPLETED,
        )
        msg_id = self.memory_store.store_message(msg)
        msg.message_id = msg_id

        self.event_bus.publish(
            AgentEvent(
                event_type=AgentEventType.MESSAGE_RECEIVED,
                payload={"session_id": sid, "text": text, "message_id": msg_id},
            )
        )
        return msg

    def record_assistant_message(
        self,
        text: str,
        session_id: str | None = None,
        status: MessageStatus = MessageStatus.COMPLETED,
        model: str | None = None,
        provider_id: str | None = None,
        interruption_reason: str | None = None,
    ) -> str:
        """Persist assistant message and emit events."""
        sid = session_id or self._active_session_id
        model_name = model or self.settings.gemini_model
        msg = ConversationMessage(
            role=MessageRole.ASSISTANT,
            content=text,
            session_id=sid,
            status=status,
            model=model_name,
            provider_id=provider_id,
            interruption_reason=interruption_reason,
        )
        msg_id = self.memory_store.store_message(msg)

        if status == MessageStatus.COMPLETED:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.MESSAGE_SENT,
                    payload={"session_id": sid, "text": text, "message_id": msg_id},
                )
            )
        return msg_id

    def update_assistant_message(
        self,
        message_id: str,
        text: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        interruption_reason: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Update content and status of an in-flight assistant message."""
        self.memory_store.update_message_content(
            message_id=message_id,
            content=text,
            status=status,
            interruption_reason=interruption_reason,
            provider_id=provider_id,
            model_id=model_id,
        )

    def process_agent_task(
        self,
        goal: str,
        session_id: str | None = None,
        context: ExecutionContext | None = None,
        wait_for_approval: bool = False,
    ) -> ExecutionOutcome:
        """Phase 3 Full Agent Task Orchestration: Analysis -> Planning -> Execution -> Completion."""
        active_session = session_id or self._active_session_id
        ctx = context or self._current_context
        ctx.session_id = active_session

        # 1. State: ANALYZING
        self.state_machine.transition_to(AgentState.ANALYZING, reason="Analyzing user goal")

        # Phase 5: Retrieve relevant memories and build bounded context safely
        if (
            self.settings.memory_enabled
            and self.settings.memory_allow_cloud_transmission
            and not ctx.memory_context
        ):
            try:
                ctx.memory_context = self.memory_manager.build_memory_context(
                    query=goal, project_id=ctx.project_id, for_cloud_transmission=True
                )
            except Exception as exc:
                logger.warning(f"Memory context retrieval encountered safe error: {exc}")
                ctx.memory_context = ""

        # 2. Check if planning is required
        needs_plan = self.planner.should_plan(goal)
        available_tool_defs = [
            t.get_definition()
            for t in self.tool_registry.list_tools()
            if hasattr(t, "get_definition")
        ]

        if not needs_plan:
            # Direct conversational path
            self.state_machine.transition_to(
                AgentState.EXECUTING, reason="Executing single-turn conversational reply"
            )
            try:
                history = self.get_session_history(session_id=active_session)
                effective_prompt = f"{ctx.memory_context}\n\n{goal}" if ctx.memory_context else goal
                resp = self.ai_provider.generate_text(prompt=effective_prompt, history=history)
                self.state_machine.transition_to(
                    AgentState.COMPLETED, reason="Direct reply finished"
                )
                plan = Plan(goal=goal, session_id=active_session)
                return ExecutionOutcome(
                    status="completed", plan=plan, final_response=resp.text, steps_executed=1
                )
            except Exception as exc:
                self.state_machine.transition_to(AgentState.FAILED, reason=str(exc))
                plan = Plan(goal=goal, session_id=active_session)
                return ExecutionOutcome(status="failed", plan=plan, error=str(exc))

        # 3. State: PLANNING
        self.state_machine.transition_to(AgentState.PLANNING, reason="Decomposing multi-step task")
        history = self.get_session_history(session_id=active_session)

        try:
            plan = self.planner.create_plan(
                goal=goal,
                context=ctx,
                available_tools=available_tool_defs,
                history=history,
            )
        except Exception as exc:
            self.state_machine.transition_to(AgentState.FAILED, reason=f"Planning failed: {exc}")
            empty_plan = Plan(goal=goal, session_id=active_session)
            return ExecutionOutcome(status="failed", plan=empty_plan, error=str(exc))

        # 4. State: PLAN_READY
        self.state_machine.transition_to(
            AgentState.PLAN_READY, reason="Plan generated and validated"
        )

        # 5. State: EXECUTING
        outcome = self.executor.execute_plan(
            plan=plan, context=ctx, wait_for_approval=wait_for_approval
        )
        return outcome

    def submit_approval_decision(
        self,
        proposal_id: str,
        approved: bool,
        session_id: str,
        reason: str = "",
    ) -> bool:
        """Submit user approval or rejection for a pending proposal."""
        return self.approval_manager.submit_decision(
            proposal_id=proposal_id,
            approved=approved,
            session_id=session_id,
            reason=reason,
        )

    def get_pending_proposal(self, session_id: str) -> ToolProposal | None:
        """Get the active pending proposal for the given session."""
        return self.approval_manager.get_pending_proposal(session_id=session_id)

    def process_user_message(self, text: str, session_id: str | None = None) -> str:
        """Process a user message through JARVIS (backward-compatible API)."""
        active_session = session_id or self._active_session_id
        self.record_user_message(text=text, session_id=active_session)

        if not self.ai_provider.is_ready():
            notice = (
                "[AI Provider Notice] Active AI provider is not configured. "
                "Please configure your API key in Settings (⚙) or in the .env file."
            )
            self.record_assistant_message(
                text=notice,
                session_id=active_session,
                status=MessageStatus.COMPLETED,
            )
            return notice

        outcome = self.process_agent_task(goal=text, session_id=active_session)
        reply = outcome.final_response or outcome.error or "Task completed."

        status = MessageStatus.COMPLETED if outcome.status == "completed" else MessageStatus.FAILED
        self.record_assistant_message(
            text=reply,
            session_id=active_session,
            status=status,
        )
        return reply

    # Phase 5 Persistent Memory Management APIs
    def build_memory_context(
        self,
        query: str,
        project_id: str | None = None,
        for_cloud_transmission: bool = True,
    ) -> str:
        """Retrieve relevant memories and format into a bounded context string."""
        return self.memory_manager.build_memory_context(
            query, project_id=project_id, for_cloud_transmission=for_cloud_transmission
        )

    def extract_memory_candidates(
        self,
        text: str,
        session_id: str | None = None,
        message_id: str | None = None,
        project_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Identify memory candidates from user input and persist in PENDING_APPROVAL status."""
        sid = session_id or self._active_session_id
        return self.memory_manager.extract_and_propose_candidates(
            text=text,
            session_id=sid,
            message_id=message_id,
            project_id=project_id,
        )

    def approve_memory_candidate(self, candidate_id: str) -> MemoryRecord | None:
        """Approve and activate a pending memory candidate with conflict resolution."""
        return self.memory_manager.approve_candidate(candidate_id)

    def reject_memory_candidate(self, candidate_id: str) -> bool:
        """Reject and delete a pending memory candidate."""
        return self.memory_manager.reject_candidate(candidate_id)

    def remember(
        self,
        content: str,
        category: MemoryCategory = MemoryCategory.PREFERENCE,
        key: str = "",
        project_id: str | None = None,
        importance: float = 0.5,
    ) -> MemoryRecord:
        """Create and immediately activate an approved memory record."""
        return self.memory_manager.create_approved_memory(
            content=content,
            category=category,
            key=key,
            project_id=project_id,
            importance=importance,
            source_conversation_id=self._active_session_id,
        )

    def delete_memory(self, memory_id: str, soft: bool = True) -> bool:
        """Delete a memory record."""
        return self.memory_manager.delete_memory(memory_id, soft=soft)

    def list_memories(
        self,
        category: MemoryCategory | None = None,
        status: MemoryStatus | None = None,
        project_id: str | None = None,
        user_approved_only: bool = False,
        search_query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List stored memories with filtering and search."""
        return self.memory_manager.list_memories(
            category=category,
            status=status,
            project_id=project_id,
            user_approved_only=user_approved_only,
            search_query=search_query,
            limit=limit,
            offset=offset,
        )

    def shutdown(self) -> None:
        """Gracefully release resources and close subsystems."""
        if self.state_machine.current_state == AgentState.CANCELLED:
            return

        logger.info("Shutting down JARVIS agent core...")
        try:
            if self.state_machine.can_transition(AgentState.CANCELLED):
                self.state_machine.transition_to(
                    AgentState.CANCELLED, reason="Application shutdown initiated"
                )
        except Exception:
            pass

        self._current_context.cancel()
        if hasattr(self, "browser_service") and self.browser_service:
            try:
                self.browser_service.close()
            except Exception as exc:
                logger.warning(f"Error closing browser service: {exc}")
        try:
            self.memory_manager.close()
        except Exception as exc:
            logger.warning(f"Error closing memory manager: {exc}")
        try:
            self.memory_store.close()
        except Exception as exc:
            logger.warning(f"Error closing memory store: {exc}")
        self.event_bus.clear()
        logger.info("JARVIS agent core shutdown complete.")
