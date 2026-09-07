# Fork notes

This is a personal fork of [DevilXD/TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner)
(MIT licensed — original copyright retained in `LICENSE`).

## What this fork adds

A **"This Week"** tab (`WeeklyPicker` in `gui.py`) that makes selecting campaigns quicker:

- Lists the drop campaigns for the coming week — every **active** campaign plus **upcoming**
  ones starting within 7 days — as a checkbox list, read directly from the live inventory.
- **Hides campaigns you can't complete**: sub-only campaigns, ones already fully claimed, and
  ones where there isn't enough time left to earn the required watch minutes
  (`campaign.availability < 1.0`).
- **🔗 Link account** button on any campaign your account isn't linked to — opens that
  campaign's Twitch account-linking page in one click.
- **🔄 Refresh from Twitch** re-fetches the inventory (so newly-linked accounts show up), and
  the tab auto-re-renders whenever an inventory fetch completes.
- **✅ Apply selection** writes the ticked games into the priority list, switches to
  `PRIORITY_ONLY` mode, saves, and triggers a reload — so the miner immediately starts
  collecting your picks from live participating channels.

All mining/auth/channel-finding is unchanged upstream behaviour.
