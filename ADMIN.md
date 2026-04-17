## Multi-User Management

This guide explains how to use the multi-user adaptation of the Language Learning Tutor bot.  
The multi-user system uses Google Secret Manager to store user lists:

### Retrieve admin chat ID
```bash
gcloud secrets versions access latest --secret=telegram-user-id
```

```bash
# Create authorized users secret (replace with actual chat IDs)
echo -n "XXXXXXXXXX" | gcloud secrets versions add authorized-users --data-file=-
# Create admin users secret (replace with actual chat IDs)
echo -n "XXXXXXXXXX" | gcloud secrets versions add admin-users --data-file=-
```