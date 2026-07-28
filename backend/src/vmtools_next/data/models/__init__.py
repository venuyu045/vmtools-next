"""ORM models package — import all submodules to register tables with Base.metadata."""
from vmtools_next.data.models.warehouse import (  # noqa: F401
    WarehouseModel, MaterialItemModel, ContainerItemModel,
    ScanStatusModel, StorageZoneModel,
)
from vmtools_next.data.models.auth import (  # noqa: F401
    UserModel, OrganizationModel, WarehouseGroupModel,
)
from vmtools_next.data.models.logistics import (  # noqa: F401
    MccBotModel, LogisticsWaypointModel, LogisticsDropPointModel,
    LogisticsTaskTemplateModel, LogisticsTaskRunModel, LogisticsTaskLogModel,
    OperationLogModel,
)
from vmtools_next.data.models.build import (  # noqa: F401
    BuildTaskModel, BuildLayerModel,
)
from vmtools_next.data.models.build_map_art import (  # noqa: F401
    MapArtTask, MapArtMaterial, MapArtBotAssignment, MapArtBlockState,
)
from vmtools_next.data.models.mcc_session import MccMcpSessionModel  # noqa: F401
from vmtools_next.data.models.plugin import PluginStateModel  # noqa: F401
from vmtools_next.data.models.monitor import (  # noqa: F401
    AlertRuleModel, AlertHistoryModel, MetricsSnapshotModel,
)
from vmtools_next.data.models.player_tracking import PlayerTrackingOwnerModel  # noqa: F401

__all__ = [
    # warehouse
    "WarehouseModel", "MaterialItemModel", "ContainerItemModel",
    "ScanStatusModel", "StorageZoneModel",
    # auth
    "UserModel", "OrganizationModel", "WarehouseGroupModel",
    # logistics
    "MccBotModel", "LogisticsWaypointModel", "LogisticsDropPointModel",
    "LogisticsTaskTemplateModel", "LogisticsTaskRunModel", "LogisticsTaskLogModel",
    "OperationLogModel",
    # build
    "BuildTaskModel", "BuildLayerModel",
    # mcc session
    "MccMcpSessionModel",
    # plugin
    "PluginStateModel",
    # monitor
    "AlertRuleModel", "AlertHistoryModel", "MetricsSnapshotModel",
]
