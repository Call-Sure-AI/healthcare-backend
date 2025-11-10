# app/utils/latency_tracker.py - CLEAN VERSION

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

# Use clean logger
logger = logging.getLogger("latency")

@dataclass
class LatencyMetrics:
    """Store all latency measurements for a single interaction"""
    call_sid: str
    interaction_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    # User speech timings
    speech_detected_at: Optional[float] = None
    speech_ended_at: Optional[float] = None
    transcript_received_at: Optional[float] = None
    
    # AI Processing timings
    llm_request_start: Optional[float] = None
    llm_first_response: Optional[float] = None
    llm_complete: Optional[float] = None
    
    # Tool execution timings
    tool_execution_start: Optional[float] = None
    tool_execution_end: Optional[float] = None
    tool_name: Optional[str] = None
    
    # Second LLM call
    llm2_request_start: Optional[float] = None
    llm2_complete: Optional[float] = None
    
    # TTS timings
    tts_request_start: Optional[float] = None
    tts_first_chunk: Optional[float] = None
    tts_complete: Optional[float] = None
    tts_chunks_count: int = 0
    
    # Audio streaming timings
    first_audio_sent: Optional[float] = None
    last_audio_sent: Optional[float] = None
    audio_frames_sent: int = 0
    total_audio_bytes: int = 0
    
    # End-to-end
    interaction_complete: Optional[float] = None
    
    def calculate_metrics(self) -> Dict[str, float]:
        """Calculate derived latency metrics in milliseconds"""
        metrics = {}
        
        # STT latency
        if self.speech_ended_at and self.transcript_received_at:
            metrics["stt_latency"] = round((self.transcript_received_at - self.speech_ended_at) * 1000, 0)
        
        # LLM latency
        if self.llm_request_start and self.llm_first_response:
            metrics["llm_first_token"] = round((self.llm_first_response - self.llm_request_start) * 1000, 0)
        
        if self.llm_request_start and self.llm_complete:
            metrics["llm_total"] = round((self.llm_complete - self.llm_request_start) * 1000, 0)
        
        # Tool execution
        if self.tool_execution_start and self.tool_execution_end:
            metrics["tool_time"] = round((self.tool_execution_end - self.tool_execution_start) * 1000, 0)
        
        # Second LLM (after tool)
        if self.llm2_request_start and self.llm2_complete:
            metrics["llm2_total"] = round((self.llm2_complete - self.llm2_request_start) * 1000, 0)
        
        # TTS latency
        if self.tts_request_start and self.tts_first_chunk:
            metrics["tts_first_chunk"] = round((self.tts_first_chunk - self.tts_request_start) * 1000, 0)
        
        if self.tts_request_start and self.tts_complete:
            metrics["tts_total"] = round((self.tts_complete - self.tts_request_start) * 1000, 0)
        
        # ⚡ CRITICAL METRIC: Time from user stops speaking to first audio
        if self.speech_ended_at and self.first_audio_sent:
            metrics["time_to_first_audio"] = round((self.first_audio_sent - self.speech_ended_at) * 1000, 0)
        
        # Total interaction time
        if self.speech_ended_at and self.interaction_complete:
            metrics["total_time"] = round((self.interaction_complete - self.speech_ended_at) * 1000, 0)
        
        # Audio streaming
        if self.first_audio_sent and self.last_audio_sent:
            metrics["audio_duration"] = round((self.last_audio_sent - self.first_audio_sent) * 1000, 0)
        
        metrics["tts_chunks"] = self.tts_chunks_count
        metrics["audio_frames"] = self.audio_frames_sent
        metrics["audio_kb"] = round(self.total_audio_bytes / 1024, 1)
        
        return metrics
    
    def log_summary(self):
        """Log a CLEAN, READABLE summary"""
        metrics = self.calculate_metrics()
        
        # Build a clean, single-line summary for the most important metrics
        ttfa = metrics.get("time_to_first_audio", "N/A")
        total = metrics.get("total_time", "N/A")
        
        logger.info("=" * 100)
        logger.info(f"📊 LATENCY SUMMARY")
        logger.info(f"   Call: {self.call_sid[-8:]}")  # Last 8 chars only
        logger.info(f"   Interaction: {self.interaction_id[:8]}")  # First 8 chars only
        logger.info("=" * 100)
        
        # Critical metrics first
        logger.info(f"⚡ TIME TO FIRST AUDIO: {ttfa}ms")
        logger.info(f"⏱️  TOTAL INTERACTION: {total}ms")
        logger.info("-" * 100)
        
        # Detailed breakdown
        if "llm_total" in metrics:
            logger.info(f"   LLM: {metrics['llm_total']}ms")
        
        if self.tool_name and "tool_time" in metrics:
            logger.info(f"   Tool ({self.tool_name}): {metrics['tool_time']}ms")
        
        if "llm2_total" in metrics:
            logger.info(f"   LLM (after tool): {metrics['llm2_total']}ms")
        
        if "tts_first_chunk" in metrics:
            logger.info(f"   TTS first chunk: {metrics['tts_first_chunk']}ms")
        
        if "tts_total" in metrics:
            logger.info(f"   TTS complete: {metrics['tts_total']}ms")
        
        if "audio_duration" in metrics:
            logger.info(f"   Audio streaming: {metrics['audio_duration']}ms")
        
        logger.info("-" * 100)
        logger.info(f"   Audio: {metrics.get('tts_chunks', 0)} chunks, {metrics.get('audio_kb', 0)} KB")
        logger.info("=" * 100)
        
        return metrics
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        metrics = self.calculate_metrics()
        return {
            "call_sid": self.call_sid,
            "interaction_id": self.interaction_id,
            "timestamp": self.timestamp.isoformat(),
            "tool_used": self.tool_name,
            "metrics": metrics
        }


class LatencyTracker:
    """Global latency tracker"""
    
    def __init__(self):
        self.active_metrics: Dict[str, LatencyMetrics] = {}
        self.completed_metrics: List[Dict] = []
    
    def start_interaction(self, call_sid: str, interaction_id: str) -> LatencyMetrics:
        """Start tracking a new interaction"""
        metrics = LatencyMetrics(call_sid=call_sid, interaction_id=interaction_id)
        self.active_metrics[interaction_id] = metrics
        return metrics
    
    def get_metrics(self, interaction_id: str) -> Optional[LatencyMetrics]:
        """Get metrics for an interaction"""
        return self.active_metrics.get(interaction_id)
    
    def complete_interaction(self, interaction_id: str):
        """Mark interaction as complete and log summary"""
        if interaction_id in self.active_metrics:
            metrics = self.active_metrics[interaction_id]
            metrics.interaction_complete = time.time()
            
            # Log clean summary
            calculated_metrics = metrics.log_summary()
            
            # Store for analytics
            self.completed_metrics.append(metrics.to_dict())
            
            # Remove from active
            del self.active_metrics[interaction_id]
            
            return calculated_metrics
        return None
    
    def get_session_stats(self, call_sid: str) -> Dict:
        """Get aggregate stats for a call session"""
        session_metrics = [m for m in self.completed_metrics if m["call_sid"] == call_sid]
        
        if not session_metrics:
            return {}
        
        ttfa_values = [m["metrics"].get("time_to_first_audio") for m in session_metrics if "time_to_first_audio" in m["metrics"]]
        
        if ttfa_values:
            stats = {
                "total_interactions": len(session_metrics),
                "avg_ttfa_ms": round(sum(ttfa_values) / len(ttfa_values), 0),
                "min_ttfa_ms": round(min(ttfa_values), 0),
                "max_ttfa_ms": round(max(ttfa_values), 0),
            }
            logger.info(f"📈 SESSION STATS: {stats}")
            return stats
        
        return {}


# Global instance
latency_tracker = LatencyTracker()