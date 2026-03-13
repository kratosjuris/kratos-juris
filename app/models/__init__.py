# torna a pasta app/models um package
# app/models/__init__.py
from app.models.user import User
from app.models.permission import Permission
from app.models.user_permission import UserPermission
from app.models.audit_log import AuditLog

__all__ = ["User", "Permission", "UserPermission", "AuditLog"]
