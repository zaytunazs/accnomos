# Making the repository private (not before 16 Dec 2026)

Both hackathons require a public repository. The Meta community vote closes on 16 Nov; the PayPal AI Hackathon judges
from 1 to 15 Dec and needs the repository public and the project testable until judging ends (15 Dec 2026), so keep it
public until at least 16 Dec. This list is what breaks when it goes
private and what to do first.

## Before flipping

1. **Website deploy (Plesk).** The `site` branch is pulled by Plesk Git into `httpdocs`. If Plesk pulls over
   anonymous HTTPS, switch it to SSH with a read-only deploy key:
   - Plesk › Git › the accnomos repository › copy its SSH public key (or generate one).
   - GitHub › Settings › Deploy keys › Add (read-only). Change the Plesk remote to `git@github.com:zaytunazs/accnomos.git`.
   - Push a trivial web change and check accnomos.com updates.
2. **API deploy (the Spark server).** `~/spark/accnomos/deploy-repo` fetches `origin main`. Check its remote with
   `git -C ~/spark/accnomos/deploy-repo remote -v`. If it is `https://github.com/...` without credentials, add a
   second read-only deploy key from the Spark (`ssh-keygen -t ed25519 -f ~/.ssh/accnomos_deploy`) and switch the remote
   to SSH. Run `jobs/api_up.sh` once and check `https://api.accnomos.com/health`.
3. **Android APK links.** Release downloads on a private repository need a GitHub login, so the links in `README.md`
   and `docs/submission/JUDGING.md` stop working for the public. Once the Play listing is live, point people there;
   otherwise host the APK on accnomos.com (e.g. `/download/accnomos-<version>.apk`) and update the links.
4. **CodeQL.** Code scanning on private repositories needs GitHub Advanced Security. `codeql.yml` now skips itself when
   the repository is private, so it shows as skipped rather than failed. Dependabot keeps working.
5. **Actions minutes.** Private repositories on the Free plan get 2,000 Actions minutes a month; one full CI run
   (pytest ×5, ruff, pyright, web, e2e up to 35 min, Flutter) is roughly an hour of runner time. Push to branches in
   batches, or move to GitHub Pro / Team, or run the e2e job on main only.
6. **Submission mode.** The web deploy reads repo variable `SUBMISSION_MODE` (default `1` = judged site). Set it to
   `0` when you want the normal post-hackathon wording, then re-run "Deploy web".

## Flip

GitHub › Settings › General › Danger Zone › Change visibility › Private. Or from a machine with `gh` logged in as the
owner: `gh repo edit zaytunazs/accnomos --visibility private --accept-visibility-change-consequences`.

Note: stars and watchers from other people are removed when a public repository goes private, and forks stay public.

## After flipping

- Check accnomos.com, `https://api.accnomos.com/health`, and that CI runs on the next push.
- Remove the GitHub repository link from the site footer / docs if it is shown to customers.
