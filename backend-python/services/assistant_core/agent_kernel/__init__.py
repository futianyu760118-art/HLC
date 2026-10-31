"""LLM-first Agent Kernel for HRM assistant orchestration.

This package is the new architecture boundary for ordinary assistant traffic.
The legacy Skill-first runtime now acts as compatibility wiring around this
kernel while business handlers, permissions, audit and rich responses remain
inside their existing modules.
"""

from .kernel import AgentKernel
from .planning import SkillPlan
from .services import AgentKernelServices
from .state import AgentKernelRunState, KernelNodeEvent, SlotReferenceResolution
from .skill_playbook import SkillPlaybook
from .tool_workbench import ToolInvocation, ToolWorkbench, ToolWorkbenchError
from . import confirmations, context, execution, policy

__all__ = [
    'AgentKernel',
    'AgentKernelRunState',
    'AgentKernelServices',
    'KernelNodeEvent',
    'SkillPlaybook',
    'SkillPlan',
    'SlotReferenceResolution',
    'ToolInvocation',
    'ToolWorkbench',
    'ToolWorkbenchError',
    'confirmations',
    'context',
    'execution',
    'policy',
]
