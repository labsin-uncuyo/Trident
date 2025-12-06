# GHOSTS driver notes

- The previous dummy SSH key was removed to avoid committing secrets. Provide your own key at build time or adapt the driver to use password-based SSH against `lab_compromised` before rebuilding.
- `images/ghosts_driver/Dockerfile` no longer copies `john_scott_dummy/id_rsa`; `entrypoint.sh` will exit early if `/root/.ssh/id_rsa` is missing. Replace that check or inject a key to restore connectivity.
- The GHOSTS source (`GHOSTS/`) must be available at build time for the driver image to compile the client. Restore the upstream repo or point the build to a released artifact.
