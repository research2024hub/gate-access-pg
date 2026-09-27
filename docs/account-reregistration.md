# Resident re-registration

`POST /account/signup` now requires an `Authorization: Bearer <token>` header
for both new and returning residents. The token must belong to a live user.
The optional body `user_id` must match the token; it cannot select another user.
The existing estate, address, name, identity and contact fields remain required.

When the estate, ID type and ID number match a retained identity, signup reopens
an account only if that identity has exactly one account holder, belonging to
the authenticated user, that account is deleted, and it is not a sub-account.
Other matches return 409. A user who already has a non-deleted membership in
that estate also receives 409, including when it is awaiting approval.

A successful re-registration returns 200 and the existing account and identity
IDs, with `is_active: false`. The account is
no longer deleted, so it appears in `GET /account/estate/{estate_id}`. Its address
is updated and its old account OTP is cleared. Retained identity details and
access records are preserved for administrator review. No access is enabled by
submitting the request. Fresh resident signup still returns 201.

## Administrator integration

Use the existing inactive-account list and Activate/Delete actions. Returning
residents follow the same approval flow as new residents; no additional response
flags, request flags, or confirmation controls are required.

Approve with `POST /account/activate`:

```json
{
  "account_holder_id": 123
}
```

Only an authorized account manager can approve. Activation may make retained
privileges, vehicles and guest access eligible again, subject to existing access
checks. Administrators can amend those records through the existing management
tools. The activation notification targets the resident. Re-registration and
activation are recorded in the audit log.

Decline with `DELETE /account/delete` and the same `account_holder_id`. This
soft-deletes the account again, keeping access blocked and history intact.
A deleted account cannot be activated until its owner submits another valid
re-registration request.

This implementation uses existing database columns and logs; it adds no migration.
It assumes the soft-delete and logs migrations required by the API are installed.
Signup still requires the resident's login token. If the frontend already sends
it, no changes are needed for the existing approval controls.
