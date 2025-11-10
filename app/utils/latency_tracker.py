# app/utils/latency_tracker.py

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

logger = logging.getLogger(__name__)

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
    
    # Tool execution timings (if applicable)
    tool_execution_start: Optional[float] = None
    tool_execution_end: Optional[float] = None
    tool_name: Optional[str] = None
    
    # Second LLM call (if tool was used)
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
        """Calculate derived latency metrics"""
        metrics = {}
        
        if self.speech_ended_at and self.transcript_received_at:
            metrics["stt_latency"] = round((self.transcript_received_at - self.speech_ended_at) * 1000, 2)
        
        if self.transcript_received_at and self.llm_first_response:
            metrics["llm_time_to_first_token"] = round((self.llm_first_response - self.transcript_received_at) * 1000, 2)
        
        if self.llm_request_start and self.llm_complete:
            metrics["llm_total_time"] = round((self.llm_complete - self.llm_request_start) * 1000, 2)
        
        if self.tool_execution_start and self.tool_execution_end:
            metrics["tool_execution_time"] = round((self.tool_execution_end - self.tool_execution_start) * 1000, 2)
        
        if self.llm2_request_start and self.llm2_complete:
            metrics["llm2_total_time"] = round((self.llm2_complete - self.llm2_request_start) * 1000, 2)
        
        if self.tts_request_start and self.tts_first_chunk:
            metrics["tts_time_to_first_chunk"] = round((self.tts_first_chunk - self.tts_request_start) * 1000, 2)
        
        if self.tts_request_start and self.tts_complete:
            metrics["tts_total_time"] = round((self.tts_complete - self.tts_request_start) * 1000, 2)
        
        if self.tts_first_chunk and self.first_audio_sent:
            metrics["audio_buffer_delay"] = round((self.first_audio_sent - self.tts_first_chunk) * 1000, 2)
        
        # CRITICAL METRIC: Time from user stops speaking to first audio plays
        if self.speech_ended_at and self.first_audio_sent:
            metrics["time_to_first_audio_ms"] = round((self.first_audio_sent - self.speech_ended_at) * 1000, 2)
        
        # CRITICAL METRIC: Total interaction time
        if self.speech_ended_at and self.interaction_complete:
            metrics["total_interaction_time_ms"] = round((self.interaction_complete - self.speech_ended_at) * 1000, 2)
        
        # Audio streaming metrics
        if self.first_audio_sent and self.last_audio_sent:
            metrics["audio_streaming_duration_ms"] = round((self.last_audio_sent - self.first_audio_sent) * 1000, 2)
        
        metrics["tts_chunks_generated"] = self.tts_chunks_count
        metrics["audio_frames_sent"] = self.audio_frames_sent
        metrics["total_audio_kb"] = round(self.total_audio_bytes / 1024, 2)
        
        return metrics
    
    def log_summary(self):
        """Log a comprehensive summary of all latencies"""
        metrics = self.calculate_metrics()
        
        logger.info("=" * 100)
        logger.info(f"📊 LATENCY REPORT - Call: {self.call_sid} | Interaction: {self.interaction_id}")
        logger.info("=" * 100)
        
        # Critical user-facing metrics
        if "time_to_first_audio_ms" in metrics:
            logger.info(f"⚡ TIME TO FIRST AUDIO: {metrics['time_to_first_audio_ms']}ms")
        
        if "total_interaction_time_ms" in metrics:
            logger.info(f"⏱️  TOTAL INTERACTION: {metrics['total_interaction_time_ms']}ms")
        
        logger.info("-" * 100)
        
        # Detailed breakdown
        logger.info("🔍 DETAILED BREAKDOWN:")
        
        if "stt_latency" in metrics:
            logger.info(f"   STT (Speech-to-Text): {metrics['stt_latency']}ms")
        
        if "llm_time_to_first_token" in metrics:
            logger.info(f"   LLM Time to First Token: {metrics['llm_time_to_first_token']}ms")
        
        if "llm_total_time" in metrics:
            logger.info(f"   LLM Total Processing: {metrics['llm_total_time']}ms")
        
        if self.tool_name and "tool_execution_time" in metrics:
            logger.info(f"   Tool Execution ({self.tool_name}): {metrics['tool_execution_time']}ms")
        
        if "llm2_total_time" in metrics:
            logger.info(f"   LLM Second Call: {metrics['llm2_total_time']}ms")
        
        if "tts_time_to_first_chunk" in metrics:
            logger.info(f"   TTS Time to First Chunk: {metrics['tts_time_to_first_chunk']}ms")
        
        if "tts_total_time" in metrics:
            logger.info(f"   TTS Total Generation: {metrics['tts_total_time']}ms")
        
        if "audio_buffer_delay" in metrics:
            logger.info(f"   Audio Buffer Delay: {metrics['audio_buffer_delay']}ms")
        
        if "audio_streaming_duration_ms" in metrics:
            logger.info(f"   Audio Streaming Duration: {metrics['audio_streaming_duration_ms']}ms")
        
        logger.info("-" * 100)
        
        # Audio metrics
        logger.info(f"📦 AUDIO METRICS:")
        logger.info(f"   TTS Chunks: {metrics.get('tts_chunks_generated', 0)}")
        logger.info(f"   Audio Frames: {metrics.get('audio_frames_sent', 0)}")
        logger.info(f"   Total Audio Size: {metrics.get('total_audio_kb', 0)} KB")
        
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
            "metrics": metrics,
            "raw_timings": {
                "speech_ended_at": self.speech_ended_at,
                "transcript_received_at": self.transcript_received_at,
                "llm_request_start": self.llm_request_start,
                "llm_complete": self.llm_complete,
                "tts_first_chunk": self.tts_first_chunk,
                "first_audio_sent": self.first_audio_sent,
                "interaction_complete": self.interaction_complete,
            }
        }


class LatencyTracker:
    """Global latency tracker for all calls"""
    
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
        """Mark interaction as complete and store metrics"""
        if interaction_id in self.active_metrics:
            metrics = self.active_metrics[interaction_id]
            metrics.interaction_complete = time.time()
            
            # Log summary
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
        
        # Calculate averages
        ttfa_values = [m["metrics"].get("time_to_first_audio_ms") for m in session_metrics if "time_to_first_audio_ms" in m["metrics"]]
        
        stats = {
            "total_interactions": len(session_metrics),
            "avg_time_to_first_audio_ms": round(sum(ttfa_values) / len(ttfa_values), 2) if ttfa_values else None,
            "min_time_to_first_audio_ms": round(min(ttfa_values), 2) if ttfa_values else None,
            "max_time_to_first_audio_ms": round(max(ttfa_values), 2) if ttfa_values else None,
        }
        
        return stats


# Global instance
latency_tracker = LatencyTracker()