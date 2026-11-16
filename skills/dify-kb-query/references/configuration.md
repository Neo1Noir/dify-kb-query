# Configuration

The client reads `scripts/config.json`, or the file named by `DIFY_KB_CONFIG`. It accepts exactly `api_base_url` and `required_tags`. Tags are selected by UUID; display names can change on the server.

An administrator supplies the endpoint and tags. Sample hosts and IDs are placeholders. Prefer HTTPS for remote access. Explicitly configured HTTP is supported for trusted local deployments and does not encrypt credentials on the transport.

Supply `DIFY_KB_API_KEY` to the client process using a Knowledge API key. Never put it in config.json, source files, screenshots, chat, or release archives. The client neither enumerates environment variables nor prints the key.

Windows users can run `python scripts/setup_key.py` in their own terminal for hidden input and current-user persistence. `--status` prints presence/source only; `--replace` is for an explicitly requested replacement. Other systems use their approved secret manager or launch environment; the helper does not persist keys there.

Tag and dataset discovery endpoints may require a workspace-wide Dify key. A scoped credential's 403 is not permission to broaden access. Refer the decision to the administrator. See [Dify key scopes](https://docs.dify.ai/en/api-reference/guides/knowledge-base-api).

Remote ChatGPT runtimes do not inherit laptop credentials or intranet access. If a runtime cannot safely receive the key or reach Dify, explain the missing capability and stop. Installing a ZIP does not establish connectivity.

For upgrades, preserve configuration outside the skill through `DIFY_KB_CONFIG`, review the new version, and deliberately replace the old installation. The installer refuses automatic overwrite.
