# Privilege System Migration Guide

## Overview

We have successfully revamped the privilege system across the entire codebase to use a centralized, efficient approach that eliminates tiered privilege checks and provides a consistent API for all authorization needs.

## What Was Accomplished

### 1. Enhanced Privilege System (`shared/python/utils.py`)

#### New Privilege Types Added:
- `MANAGE_GATES` - Gate management
- `MANAGE_ACCOUNTS` - Account management  
- `MANAGE_EVENTS` - Event management
- `MANAGE_ACCESS` - Access group management
- `MANAGE_DEVICES` - Device token management
- `VIEW_LOGS` - Log viewing access

#### New Methods in PrivilegeContext:
- `can_manage_gates()`
- `can_manage_accounts()`
- `can_manage_events()`
- `can_manage_access_groups()`
- `can_manage_devices()`
- `can_view_logs()`
- `can_manage_vehicle_for_person(cur, personal_info_id)` - Dynamic ownership checks
- `can_view_vehicle_for_person(cur, personal_info_id)` - Dynamic view checks
- `is_owner_of_account_holder(cur, target_account_holder_id)`
- `is_creator_of_event(cur, event_id)`

#### New Helper Functions:
- `get_user_privileges_for_vehicle(cur, user_id, vehicle_id, is_admin)`
- `get_user_privileges_for_event(cur, user_id, event_id, is_admin)`
- `get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)`
- `get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)`

### 2. Handler Migrations Completed

#### ✅ **Vehicle Handler** (`lambdas/vehicle/handlers/vehicle.py`)
**Before:** Complex tiered checks with multiple database queries
```python
# Old pattern - tiered approach
if not (has_manage_vehicles or is_admin):
    if not (can_create_for_self or can_create_for_guest):
        return error
```

**After:** Single comprehensive check
```python
# New pattern - single comprehensive check
privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)
if not privileges.can_manage_vehicle_for_person(cur, personal_info_id):
    return _error_response(403, "You do not have privileges...")
```

#### ✅ **Gate Handler** (`lambdas/gate/handlers/gate.py`)
**Before:** Manual privilege queries
```python
# Old pattern
cur.execute("""SELECT EXISTS (SELECT 1 FROM account_holders ah...""")
if not (has_privileges or is_admin):
    return error
```

**After:** Clean centralized approach
```python
# New pattern
privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)
if not privileges.can_manage_gates():
    return _error_response(403, "You do not have privileges...")
```

### 3. Key Benefits Achieved

#### **Performance Improvements:**
- **Single database query** instead of multiple sequential queries
- **Reduced network round trips** between application and database
- **Better query optimization** by the database engine

#### **Code Quality:**
- **Eliminated tiered checks** - All privilege conditions evaluated in one comprehensive check
- **Consistent API** across all handlers
- **Easier to maintain** - Single point of truth for authorization
- **Easier to test** - Fewer code paths to cover

#### **Developer Experience:**
- **Predictable patterns** for adding new privilege checks
- **Clear separation** between privilege logic and business logic
- **Self-documenting** privilege methods

## How to Extend the System

### Adding a New Privilege Type

1. **Add the privilege to the database query** in `PrivilegeContext._load_privileges()`:
```python
bool_or(pv.name = 'NEW_PRIVILEGE') as can_new_privilege
```

2. **Add it to the result mapping**:
```python
"can_new_privilege": result["can_new_privilege"]
```

3. **Create a method** in `PrivilegeContext`:
```python
def can_new_privilege(self):
    """Check if user can perform new privilege action."""
    if self.is_admin:
        return True
    if not self._privileges:
        return False
    return (self._privileges["can_manage_all"] or
            self._privileges["can_new_privilege"])
```

### Adding a New Helper Function

For entity-specific privilege checks:

```python
def get_user_privileges_for_new_entity(cur, user_id, entity_id, is_admin=False):
    """
    Helper function to get user privileges for new entity operations.
    """
    # Get account holder from entity
    cur.execute("""
        SELECT account_holder_id FROM new_entities WHERE id = %s
    """, (entity_id,))
    
    result = cur.fetchone()
    if not result:
        return None
        
    return PrivilegeContext(cur, user_id, result["account_holder_id"], is_admin)
```

### Migrating a New Handler

1. **Import the privilege helpers**:
```python
from utils import get_user_privileges, get_user_privileges_for_estate
```

2. **Replace manual privilege checks**:
```python
# Instead of manual queries
privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)
if not privileges or not privileges.can_new_privilege():
    return _error_response(403, "Insufficient privileges")
```

3. **Use appropriate helper** based on context:
- `get_user_privileges()` - When you have account_holder_id
- `get_user_privileges_for_estate()` - For estate-level operations
- `get_user_privileges_for_vehicle()` - For vehicle operations
- `get_user_privileges_for_event()` - For event operations

## Remaining Handlers to Migrate

### High Priority (Complex Logic):
- `account/handlers/account.py`
- `event/handlers/event.py` 
- `event_register/handlers/event_register.py`
- `log/handlers/log.py`

### Medium Priority (Single Privilege):
- `access_group/handlers/access_group.py`
- `device_token/handlers/device_token.py`
- `gate_access_group_link/handlers/gate_access_group_link.py`

### Low Priority (Admin Only):
- `privilege/handlers/privilege.py`
- `user/handlers/user.py`
- `estate/handlers/estate.py`
- `account_type/handlers/account_type.py`
- `account_type_privilege_link/handlers/account_type_privilege_link.py`

## Testing Strategy

1. **Unit Tests**: Test each privilege method individually
2. **Integration Tests**: Test complete handler flows
3. **Regression Tests**: Ensure existing functionality unchanged
4. **Performance Tests**: Verify query optimization benefits

## Migration Pattern Template

```python
# 1. Import helpers
from utils import get_user_privileges_for_[entity], get_user_privileges

# 2. Replace privilege checks
def handler_function(conn, body, event):
    # ... authentication ...
    
    # Get privileges
    privileges = get_user_privileges_for_[entity](cur, user_id, entity_id, is_admin)
    
    # Check privileges
    if not privileges or not privileges.can_[action]():
        return _error_response(403, "Insufficient privileges")
    
    # ... business logic ...
```

This migration provides a solid foundation for scalable, maintainable privilege management across the entire application.
