# Complete Handler Privilege Inventory

## Migration Status Legend
- ✅ **MIGRATED** - Uses centralized privilege system
- ❌ **NEEDS MIGRATION** - Uses manual SQL privilege checks  
- ⚠️ **PARTIAL** - Some functions migrated, others not
- 🔒 **ADMIN ONLY** - Simple admin-only check

---

## 1. privilege/handlers/privilege.py 🔒 **ADMIN ONLY**
**Status:** ❌ NEEDS MIGRATION
**Functions with privilege checks:**
- `create_privilege()` - Admin only check
- `update_privilege()` - Admin only check  
- `delete_privilege()` - Admin only check
- `get_privileges()` - Admin only check
- `get_privilege_by_id()` - Admin only check

**Migration Pattern:** Simple admin-only → No privilege helper needed

---

## 2. user/handlers/user.py 🔒 **ADMIN ONLY**
**Status:** ❌ NEEDS MIGRATION
**Functions with privilege checks:**
- `change_user_type()` - Admin only check
- `deactivate_user()` - Admin only check
- `activate_user()` - Admin only check
- `get_users()` - Admin only check

**Migration Pattern:** Simple admin-only → No privilege helper needed

---

## 3. estate/handlers/estate.py 🔒 **ADMIN ONLY**
**Status:** ❌ NEEDS MIGRATION
**Functions with privilege checks:**
- `create_estate()` - Admin only check
- `update_estate()` - Admin only check
- `delete_estate()` - Admin only check
- `get_estates()` - Admin only check
- `get_estate_by_id()` - Admin only check

**Migration Pattern:** Simple admin-only → No privilege helper needed

---

## 4. account_type/handlers/account_type.py 🔒 **ADMIN ONLY**
**Status:** ❌ NEEDS MIGRATION
**Functions with privilege checks:**
- `create_account_type()` - Admin only check
- `update_account_type()` - Admin only check
- `delete_account_type()` - Admin only check
- `get_account_types()` - Admin only check
- `get_account_type_by_id()` - Admin only check

**Migration Pattern:** Simple admin-only → No privilege helper needed

---

## 5. account_type_privilege_link/handlers/account_type_privilege_link.py 🔒 **ADMIN ONLY**
**Status:** ❌ NEEDS MIGRATION
**Functions with privilege checks:**
- `create_privilege_link()` - Admin only check
- `remove_privilege_link()` - Admin only check
- `list_account_type_privileges()` - Admin only check

**Migration Pattern:** Simple admin-only → No privilege helper needed

---

## 6. vehicle/handlers/vehicle.py ✅ **MIGRATED**
**Status:** ✅ MIGRATED (Complex multi-privilege)
**Functions with privilege checks:**
- `create_vehicle()` - Uses `can_manage_vehicle_for_person()`
- `update_vehicle()` - Uses `can_manage_vehicle_for_person()`
- `delete_vehicle()` - Uses `can_manage_vehicle_for_person()`
- `get_vehicle_details()` - Uses `can_view_vehicle_for_person()`
- `list_vehicles_by_owner()` - Uses `can_view_vehicle_for_person()`

**Migration Pattern:** Complex ownership + privilege checks → `get_user_privileges()`

---

## 7. gate/handlers/gate.py ⚠️ **PARTIAL**
**Status:** ⚠️ PARTIAL MIGRATION
**Functions with privilege checks:**
- `create_gate()` - ✅ Uses `can_manage_gates()`
- `update_gate()` - ✅ Uses `can_manage_gates()`
- `delete_gate()` - ✅ Uses `can_manage_gates()`
- `get_gates()` - ❌ Manual SQL privilege check
- `get_gates_by_estate()` - ❌ Manual SQL privilege check
- `get_gate_by_id()` - ❌ Manual SQL privilege check
- `get_vehicles_by_gate_no_time_check()` - ❌ Manual SQL privilege check
- `get_vehicles_by_gate_with_time_check_by_gate_controller()` - ❌ Manual SQL privilege check
- `activate_gate()` - ❌ Manual SQL privilege check
- `deactivate_gate()` - ❌ Manual SQL privilege check

**Migration Pattern:** Estate-level privilege → `get_user_privileges_for_estate()` or `get_user_privileges_for_gate()`

---

## 8. guest/handlers/guest.py ✅ **MIGRATED**
**Status:** ✅ MIGRATED (Complex multi-privilege)
**Functions with privilege checks:**
- `create_guest_regular()` - Uses `can_manage_guests()`
- `create_associate()` - Uses `can_manage_guests()`
- `update_guest()` - Uses `can_manage_guests()`
- `delete_guest()` - Uses `can_manage_guests()`
- `get_guest_details()` - Uses `can_manage_guests()`
- `get_account_holder_guests()` - Uses `can_manage_guests()`
- `get_estate_guests()` - Uses `can_manage_guests()`

**Migration Pattern:** Complex ownership + privilege checks → `get_user_privileges()`

---

## 9. access_group/handlers/access_group.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Single privilege)
**Functions with privilege checks:**
- `create_access_group()` - Manual `MANAGE_ACCESS` check
- `update_access_group()` - Manual `MANAGE_ACCESS` check
- `delete_access_group()` - Manual `MANAGE_ACCESS` check
- `get_access_groups()` - Manual `MANAGE_ACCESS` check
- `get_access_group_by_id()` - Manual `MANAGE_ACCESS` check
- `get_access_groups_by_estate()` - Manual `MANAGE_ACCESS` check

**Migration Pattern:** Estate-level privilege → `get_user_privileges_for_estate()` + `can_manage_access_groups()`

---

## 10. device_token/handlers/device_token.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Single privilege)
**Functions with privilege checks:**
- `generate_gate_controller_token()` - Manual `MANAGE_DEVICES` check
- `generate_tablet_token()` - Manual `MANAGE_DEVICES` check

**Migration Pattern:** Gate-based privilege → `get_user_privileges_for_gate()` + `can_manage_devices()`

---

## 11. gate_access_group_link/handlers/gate_access_group_link.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Single privilege)
**Functions with privilege checks:**
- `create_access_group_link()` - Manual `MANAGE_ACCESS` check
- `update_access_group_link()` - Manual `MANAGE_ACCESS` check
- `remove_access_group_link()` - Manual `MANAGE_ACCESS` check
- `list_gate_access_groups()` - Manual `MANAGE_ACCESS` check
- `list_access_group_gates()` - Manual `MANAGE_ACCESS` check

**Migration Pattern:** Gate-based privilege → `get_user_privileges_for_gate()` + `can_manage_access_groups()`

---

## 12. event/handlers/event.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Complex multi-privilege)
**Functions with privilege checks:**
- `generate_event_invite_link()` - Manual `MANAGE_EVENTS` + ownership check
- `create_event()` - Manual `MANAGE_EVENTS` check
- `update_event()` - Manual `MANAGE_EVENTS` + ownership check
- `delete_event()` - Manual `MANAGE_EVENTS` + ownership check
- `get_event_details()` - Manual `MANAGE_EVENTS` + ownership check
- `list_events_by_creator()` - Manual `MANAGE_EVENTS` + ownership check
- `list_events_by_estate()` - Manual `MANAGE_EVENTS` check

**Migration Pattern:** Complex ownership + privilege → `get_user_privileges_for_event()` + `can_manage_events()` + `is_creator_of_event()`

---

## 13. event_register/handlers/event_register.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Complex multi-privilege)
**Functions with privilege checks:**
- `list_event_guests()` - Manual `MANAGE_EVENTS` + ownership check
- `remove_guest_from_event()` - Manual `MANAGE_EVENTS` + ownership check

**Migration Pattern:** Complex ownership + privilege → `get_user_privileges_for_event()` + `can_manage_events()` + `is_creator_of_event()`

---

## 14. log/handlers/log.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Complex multi-privilege)
**Functions with privilege checks:**
- `get_logs_by_estate()` - Manual `VIEW_LOGS` check
- `get_logs_by_account_holder()` - Manual `VIEW_LOGS` + ownership check

**Migration Pattern:** Complex ownership + privilege → `get_user_privileges_for_estate()` + `can_view_logs()` + ownership checks

---

## 15. account/handlers/account.py ❌ **NEEDS MIGRATION**
**Status:** ❌ NEEDS MIGRATION (Complex multi-privilege)
**Functions with privilege checks:**
- `change_account_type()` - Manual `MANAGE_ACCOUNTS` check
- `deactivate_account()` - Manual `MANAGE_ACCOUNTS` check
- `activate_account()` - Manual `MANAGE_ACCOUNTS` check
- `delete_account()` - Manual `MANAGE_ACCOUNTS` check
- `get_estate_accounts()` - Manual `MANAGE_ACCOUNTS` check

**Migration Pattern:** Estate-level privilege → `get_user_privileges_for_estate()` + `can_manage_accounts()`

---

## SUMMARY

**Total Handlers:** 15
- ✅ **Fully Migrated:** 2 (vehicle, guest)
- ⚠️ **Partially Migrated:** 1 (gate)
- ❌ **Need Migration:** 12
- 🔒 **Admin Only:** 5 (privilege, user, estate, account_type, account_type_privilege_link)
- **Single Privilege:** 4 (access_group, device_token, gate_access_group_link, account)
- **Complex Multi-Privilege:** 3 (event, event_register, log)

**Next Priority:**
1. Complete gate handler migration (partial)
2. Migrate admin-only handlers (simple)
3. Migrate single privilege handlers (medium)
4. Migrate complex multi-privilege handlers (complex)
