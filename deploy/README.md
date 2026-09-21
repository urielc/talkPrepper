# Deploying Lesson Prep on a fresh droplet

Ubuntu/Debian-flavoured steps; adjust package names for another distro. Do this after the app already
works locally per the main README (talks scraped, scriptures downloaded, index built) — it's much easier
to copy a working `data/` directory over than to run the multi-hour scrape on a public box.

1. **System user and directories**

   ```bash
   sudo adduser --system --group --home /opt/lessonprep --shell /usr/sbin/nologin lessonprep
   sudo mkdir -p /var/lib/lessonprep
   sudo chown lessonprep:lessonprep /var/lib/lessonprep
   sudo chmod 700 /var/lib/lessonprep
   ```

   `LP_DATA_DIR` (`/var/lib/lessonprep`) lives outside the git clone (`/opt/lessonprep`) so the database,
   embeddings and `secret.key` are never inside a path nginx or the app's static-file serving could ever
   reach, and so a redeploy of the code never touches them.

2. **Clone and build**

   ```bash
   sudo -u lessonprep git clone <this repo> /opt/lessonprep
   cd /opt/lessonprep
   sudo -u lessonprep python3 -m venv .venv
   sudo -u lessonprep .venv/bin/pip install -r requirements.txt
   sudo -u lessonprep bash -c 'cd web && npm install && npm run build'
   ```

   The path-traversal fix (F-01) means the app can safely serve `web/dist` itself — you do not have to
   move static serving to nginx, though the `location /` block in `nginx.conf` works either way.

3. **Copy your data** (talks JSON, scriptures JSON, `app.db`, `embeddings/`) from your working local
   `data/` directory into `/var/lib/lessonprep`, owned by `lessonprep:lessonprep`. Or build it fresh on the
   box with `python -m server.cli download-scriptures` and `python -m server.cli index` (slow: several
   hours for the scrape, minutes for indexing).

4. **Environment file**

   ```bash
   sudo cp deploy/lessonprep.env.example /etc/lessonprep.env
   sudo $EDITOR /etc/lessonprep.env   # set LP_BASE_URL to your real domain, generate LP_SECRET_KEY
   sudo chmod 600 /etc/lessonprep.env
   sudo chown root:root /etc/lessonprep.env
   ```

5. **Create the first admin**

   Run it as the service user with the same environment file the unit uses (sourcing the file by hand
   would trip over its comment lines):

   ```bash
   sudo systemd-run --pty --wait --collect --uid=lessonprep --gid=lessonprep \
       --working-directory=/opt/lessonprep --property=EnvironmentFile=/etc/lessonprep.env \
       /opt/lessonprep/.venv/bin/python -m server.cli migrate --admin-email you@example.com --name "Your Name"
   ```

   Prints a set-password link using `LP_BASE_URL`. Open it once the site is reachable over HTTPS (step 7).

6. **systemd unit**

   ```bash
   sudo cp deploy/lessonprep.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now lessonprep
   sudo systemctl status lessonprep
   ```

7. **Certificate, then nginx**

   `nginx.conf` points at the Let's Encrypt paths, so obtain the certificate before enabling the full
   site. On a box where nginx already serves other sites, enable a port-80 stub for the hostname first
   and let certbot's nginx plugin answer the challenge through it (nothing is stopped):

   ```bash
   printf 'server {\n    listen 80;\n    listen [::]:80;\n    server_name your.domain.example;\n    location / { return 404; }\n}\n' \
       | sudo tee /etc/nginx/sites-available/lessonprep >/dev/null
   sudo ln -s /etc/nginx/sites-available/lessonprep /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot certonly --nginx -d your.domain.example
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/lessonprep
   sudo sed -i 's/CHANGE.ME/your.domain.example/' /etc/nginx/sites-available/lessonprep
   sudo nginx -t && sudo systemctl reload nginx
   ```

   Renewals then go through the nginx plugin automatically (`sudo certbot renew --dry-run` to confirm).
   `nginx.conf` targets nginx 1.24 (Ubuntu 24.04); on 1.25+ you may add `http2 on;` to the 443 block.

8. **Firewall**: only 80/443 need to be open to the internet; 8765 should not be (the systemd unit already
   binds it to 127.0.0.1 only).

   **Continuous deployment** (`.github/workflows/deploy.yml`): every push to `main` runs the tests, builds the
   frontend, and over SSH as the service user pulls the code, syncs `web/dist`, installs Python deps and
   restarts the unit. One-time setup: give `lessonprep` a login shell and an `authorized_keys` entry for a
   dedicated CI key, allow `lessonprep ALL=(root) NOPASSWD: /usr/bin/systemctl restart lessonprep` in
   sudoers, and set the repository secrets `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` and variables
   `DEPLOY_HOST`, `DEPLOY_USER`.

9. **Verify**: load `https://your.domain.example`, sign in with the admin link from step 5, and confirm
   `curl -sI https://your.domain.example/api/health` shows the security headers and no `server:` header.
