"""Importa todos os models para que o mapper do SQLAlchemy resolva as relações (worker, scripts)."""
from app.assets import models as _assets  # noqa: F401
from app.attachments import models as _attachments  # noqa: F401
from app.audit import models as _audit  # noqa: F401
from app.backup import models as _backup  # noqa: F401
from app.identity import models as _identity  # noqa: F401
from app.inventory_audit import models as _inventory  # noqa: F401
from app.movements import models as _movements  # noqa: F401
from app.notifications import models as _notifications  # noqa: F401
from app.organization import models as _organization  # noqa: F401
from app.service_desk import models as _service_desk  # noqa: F401
from app.sla import models as _sla  # noqa: F401
from app.stock import models as _stock  # noqa: F401
from app.whatsapp import models as _whatsapp  # noqa: F401
