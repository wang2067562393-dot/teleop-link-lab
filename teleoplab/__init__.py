"""teleoplab：遥操作链路的最小可运行实验台。"""

from teleoplab.metrics import Summary, drop_rate, jitter, percentile, summarize
from teleoplab.policy import DegradeConfig, DegradeController, profile_for
from teleoplab.protocol import Message, ProtocolError
from teleoplab.robot_sim import RobotSim

__version__ = "0.1.0"

__all__ = [
    "DegradeConfig",
    "DegradeController",
    "Message",
    "ProtocolError",
    "RobotSim",
    "Summary",
    "drop_rate",
    "jitter",
    "percentile",
    "profile_for",
    "summarize",
    "__version__",
]
