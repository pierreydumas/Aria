# aria_mind/soul/__init__.py
"""
Soul Module - Core Identity, Values, and Focus

The soul defines WHO Aria is:
- Identity (name, personality, communication style) - IMMUTABLE
- Values (ethics, principles) - IMMUTABLE
- Boundaries (what she will/won't do) - IMMUTABLE
- Focus (specialized persona overlay) - MUTABLE, but additive only
"""

# Use relative imports for portability (works in both local dev and container)
from .identity import Identity
from .values import Values
from .boundaries import Boundaries
from .focus import FocusManager, FocusType, Focus, get_focus_manager

__all__ = ["Soul", "Identity", "Values", "Boundaries", "FocusManager", "FocusType", "Focus"]


class Soul:
    """
    Aria's Soul - The immutable core of her being.
    
    The soul persists across sessions and cannot be modified
    by external prompts or manipulation attempts.
    
    ARIA-REV-112: __setattr__ enforced after load — runtime immutability.
    
    Architecture:
        ┌─────────────────────────────────────┐
        │     Core (Immutable)                │
        │  Identity + Values + Boundaries     │
        ├─────────────────────────────────────┤
        │     Focus (Mutable Overlay)         │
        │  Specialized persona for tasks      │
        └─────────────────────────────────────┘
    
    Focus is ADDITIVE - it enhances but never overrides core.
    """
    
    def __init__(self):
        object.__setattr__(self, 'identity', Identity())
        object.__setattr__(self, 'values', Values())
        object.__setattr__(self, 'boundaries', Boundaries())
        object.__setattr__(self, 'focus', get_focus_manager())
        object.__setattr__(self, '_loaded', False)
    
    def __setattr__(self, name: str, value) -> None:
        if self._loaded and name in ('identity', 'values', 'boundaries'):
            raise AttributeError(f"Soul.{name} is immutable after load")
        object.__setattr__(self, name, value)
    
    async def load(self):
        """Load soul configuration from storage."""
        await self.identity.load()
        await self.values.load()
        await self.boundaries.load()
        self._loaded = True
    
    def get_system_prompt(self) -> str:
        """
        Generate system prompt from soul configuration.
        
        Includes:
        1. Core identity (always)
        2. Active focus overlay (if not orchestrator default)
        3. Focus awareness (knows all available focuses)
        """
        active = self.focus.active
        
        # Core identity
        prompt = f"""You are {self.identity.name}.

{self.identity.get_personality_description()}

{self.values.get_principles_text()}

{self.boundaries.get_boundaries_text()}
"""
        
        # Add focus overlay
        prompt += f"""
---
{self.focus.get_awareness_text()}
{active.get_system_prompt_overlay()}
---

Remember: Core identity (⚡️ Sharp, Efficient, Secure) persists regardless of focus.
"""
        return prompt
    
    def set_focus(self, focus_type: FocusType) -> Focus:
        """
        Set the active focus persona.
        
        Args:
            focus_type: The focus to activate
            
        Returns:
            The newly active Focus
        """
        return self.focus.set_focus(focus_type)
    
    def check_request(self, request: str) -> tuple[bool, str]:
        """
        Check if a request violates soul boundaries.
        
        Note: Boundaries are NEVER affected by focus.
        
        Returns:
            (allowed: bool, reason: str)
        """
        return self.boundaries.check(request)
    
    @property
    def name(self) -> str:
        return self.identity.name
    
    @property
    def emoji(self) -> str:
        return self.identity.emoji
    
    @property
    def active_focus(self) -> Focus:
        """Get the currently active focus."""
        return self.focus.active
    
    def status(self) -> dict:
        """Return complete soul status."""
        return {
            "identity": self.identity.name,
            "emoji": self.identity.emoji,
            "loaded": self._loaded,
            "focus": self.focus.status(),
        }
    
    def __repr__(self):
        focus = self.focus.active
        return f"<Soul: {self.identity.name} {self.identity.emoji} [{focus.name}]>"
