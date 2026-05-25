"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/metrics/metrics_collector.py
Description: Global metrics collector for the Nexe system. Collects, processes and manages

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Any

from ..data.models import ModuleInfo, ModuleState, SystemMetrics

from personality._logger import get_logger
logger = get_logger(__name__)

__all__ = ['MetricsCollector']

class MetricsCollector:
  """Global metrics collection and management system for server-nexe"""
  
  def __init__(self, i18n_manager=None) -> None:
    """
    Initialize metrics collector.
    
    Args:
      i18n_manager: Optional I18nManager for translations
    """
    self.i18n = i18n_manager
    self._lock = threading.RLock()
    self._metrics_history: List[SystemMetrics] = []
    self._max_history = 1000
    self._custom_metrics: Dict[str, Any] = {}
    
    self._system_start_time = datetime.now(timezone.utc)
  
  def _get_message(self, key: str, **kwargs) -> str:
    """Get translated message or fallback"""
    if self.i18n:
      return self.i18n.t(key, **kwargs)
    
    fallbacks = {
      'metrics.updated': f"Metrics updated for {kwargs.get('module', 'unknown')}",
      'metrics.history_cleared': f"Metrics history cleared: {kwargs.get('count', 0)} entries",
      'metrics.snapshot_created': "Metrics snapshot created"
    }
    
    return fallbacks.get(key, key)
  
  def update_module_metrics(self, modules: Dict[str, ModuleInfo], 
              module_name: str, **metrics) -> None:
    """
    Update module metrics for monitoring.
    
    Args:
      modules: Dictionary of all modules
      module_name: Name of module to update
      **metrics: Metric key-value pairs to update
    """
    if module_name in modules:
      module_info = modules[module_name]
      
      with self._lock:
        for key, value in metrics.items():
          if hasattr(module_info, key):
            setattr(module_info, key, value)
        
        module_info.last_activity = datetime.now(timezone.utc)
      
      msg = self._get_message('metrics.updated', module=module_name)
      logger.debug(msg,
            component="metrics",
            module=module_name,
            **{k: v for k, v in metrics.items() if isinstance(v, (int, float, str))})  # type: ignore[arg-type]  # FP: LoggerAdapter stub rebutja **kwargs custom; runtime ok
  
  def _compute_avg_load_time(self, running_modules: list) -> float:
    if not running_modules:
      return 0.0
    load_times = [m.load_duration_ms for m in running_modules if m.load_duration_ms]
    return sum(load_times) / len(load_times) if load_times else 0.0

  def _build_system_metrics(self, modules: Dict[str, ModuleInfo], now) -> "SystemMetrics":
    total_memory = sum(m.memory_usage_mb for m in modules.values())
    avg_cpu = sum(m.cpu_usage for m in modules.values()) / max(len(modules), 1)
    running_modules = [m for m in modules.values() if m.state == ModuleState.RUNNING]
    avg_load_time = self._compute_avg_load_time(running_modules)
    uptime_seconds = (now - self._system_start_time).total_seconds()
    return SystemMetrics(
      timestamp=now,
      total_modules=len(modules),
      running_modules=len(running_modules),
      total_memory_mb=round(total_memory, 2),
      average_cpu_usage=round(avg_cpu, 2),
      average_load_time_ms=round(avg_load_time, 2),
      total_api_calls=sum(m.api_calls for m in modules.values()),
      modules_with_errors=len([m for m in modules.values() if m.error_count > 0]),
      states_breakdown=self._get_states_breakdown(modules),
      uptime_seconds=uptime_seconds
    )

  def get_system_metrics(self, modules: Dict[str, ModuleInfo]) -> "SystemMetrics":
    """
    Get comprehensive system metrics.

    Args:
      modules: Dictionary of all modules

    Returns:
      SystemMetrics snapshot
    """
    with self._lock:
      now = datetime.now(timezone.utc)
      metrics = self._build_system_metrics(modules, now)
      self._metrics_history.append(metrics)
      if len(self._metrics_history) > self._max_history:
        self._metrics_history.pop(0)
      return metrics
  
  def _get_states_breakdown(self, modules: Dict[str, ModuleInfo]) -> Dict[str, int]:
    """Get breakdown of module states"""
    states = {}
    for state in ModuleState:
      states[state.value] = len([m for m in modules.values() if m.state == state])
    return states
  
  def get_module_metrics(self, module_info: ModuleInfo) -> Dict[str, Any]:
    """
    Get metrics for a specific module.
    
    Args:
      module_info: Module information
      
    Returns:
      Dictionary of module metrics
    """
    from ..data.models import calculate_module_uptime
    
    return {
      "name": module_info.name,
      "state": module_info.state.value,
      "memory_usage_mb": module_info.memory_usage_mb,
      "cpu_usage": module_info.cpu_usage,
      "api_calls": module_info.api_calls,
      "error_count": module_info.error_count,
      "load_duration_ms": module_info.load_duration_ms,
      "start_duration_ms": module_info.start_duration_ms,
      "last_activity": module_info.last_activity.isoformat() if module_info.last_activity else None,
      "uptime_seconds": calculate_module_uptime(module_info),
      "enabled": module_info.enabled,
      "priority": module_info.priority,
      "dependencies": module_info.dependencies,
      "provides": list(module_info.provides)
    }
  
  def get_metrics_history(self, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get historical metrics.
    
    Args:
      limit: Maximum number of metrics to return
      
    Returns:
      List of historical metrics as dictionaries
    """
    with self._lock:
      recent_metrics = self._metrics_history[-limit:] if self._metrics_history else []
      
      return [
        {
          "timestamp": m.timestamp.isoformat(),
          "total_modules": m.total_modules,
          "running_modules": m.running_modules,
          "total_memory_mb": m.total_memory_mb,
          "average_cpu_usage": m.average_cpu_usage,
          "average_load_time_ms": m.average_load_time_ms,
          "total_api_calls": m.total_api_calls,
          "modules_with_errors": m.modules_with_errors,
          "states_breakdown": m.states_breakdown,
          "uptime_seconds": m.uptime_seconds
        }
        for m in recent_metrics
      ]
  
  @staticmethod
  def _timing_stats(values: list[float]) -> Dict[str, float]:
    if not values:
      return {"min_ms": 0, "max_ms": 0, "avg_ms": 0}
    return {"min_ms": min(values), "max_ms": max(values), "avg_ms": sum(values) / len(values)}

  @staticmethod
  def _resource_stats(running: list) -> Dict[str, float]:
    return {
      "total_memory_mb": sum(m.memory_usage_mb for m in running),
      "avg_cpu_percent": sum(m.cpu_usage for m in running) / len(running),
      "max_memory_mb": max(m.memory_usage_mb for m in running) if running else 0,
      "max_cpu_percent": max(m.cpu_usage for m in running) if running else 0,
    }

  @staticmethod
  def _error_rate(running: list) -> float:
    """Percentage of running modules that have encountered at least one error."""
    if not running:
      return 0.0
    return len([m for m in running if m.error_count > 0]) / len(running) * 100

  @staticmethod
  def _avg_api_calls(running: list) -> float:
    """Average number of API calls across running modules."""
    if not running:
      return 0.0
    return sum(m.api_calls for m in running) / len(running)

  def get_performance_summary(self, modules: Dict[str, ModuleInfo]) -> Dict[str, Any]:
    """Get performance summary for all modules."""
    running = [m for m in modules.values() if m.state == ModuleState.RUNNING]
    if not running:
      return {"status": "no_running_modules"}

    return {
      "total_running": len(running),
      "load_performance": self._timing_stats([m.load_duration_ms for m in running if m.load_duration_ms]),
      "start_performance": self._timing_stats([m.start_duration_ms for m in running if m.start_duration_ms]),
      "resource_usage": self._resource_stats(running),
      "error_rate": self._error_rate(running),
      "avg_api_calls": self._avg_api_calls(running),
    }
  
  def clear_metrics_history(self) -> int:
    """
    Clear metrics history.
    
    Returns:
      Number of entries cleared
    """
    with self._lock:
      count = len(self._metrics_history)
      self._metrics_history.clear()
      
      msg = self._get_message('metrics.history_cleared', count=count)
      logger.info(msg, component="metrics")
      
      return count
  
  def set_custom_metric(self, key: str, value: Any) -> None:
    """
    Set a custom system metric.
    
    Args:
      key: Metric key
      value: Metric value
    """
    with self._lock:
      self._custom_metrics[key] = value
  
  def get_custom_metric(self, key: str, default: Any = None) -> Any:
    """
    Get a custom system metric.
    
    Args:
      key: Metric key
      default: Default value if not found
      
    Returns:
      Metric value or default
    """
    with self._lock:
      return self._custom_metrics.get(key, default)
  
  def get_all_custom_metrics(self) -> Dict[str, Any]:
    """Get all custom metrics"""
    with self._lock:
      return self._custom_metrics.copy()
  
  def remove_custom_metric(self, key: str) -> bool:
    """
    Remove a custom metric.
    
    Args:
      key: Metric key to remove
      
    Returns:
      True if metric was removed, False if not found
    """
    with self._lock:
      if key in self._custom_metrics:
        del self._custom_metrics[key]
        return True
      return False
  
  def set_max_history(self, max_size: int) -> None:
    """
    Set maximum history size.
    
    Args:
      max_size: Maximum number of metrics to keep
    """
    with self._lock:
      self._max_history = max(1, max_size)
      
      if len(self._metrics_history) > self._max_history:
        self._metrics_history = self._metrics_history[-self._max_history:]
  
  def get_system_uptime(self) -> float:
    """
    Get system uptime in seconds.
    
    Returns:
      Uptime in seconds
    """
    delta = datetime.now(timezone.utc) - self._system_start_time
    return delta.total_seconds()
  
  def reset_system_start_time(self) -> None:
    """Reset system start time to now"""
    self._system_start_time = datetime.now(timezone.utc)
  
  def get_metrics_stats(self) -> Dict[str, Any]:
    """Get metrics collector statistics"""
    with self._lock:
      return {
        "history_size": len(self._metrics_history),
        "max_history": self._max_history,
        "custom_metrics_count": len(self._custom_metrics),
        "system_uptime_seconds": self.get_system_uptime(),
        "system_start_time": self._system_start_time.isoformat()
      }