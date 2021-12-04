# TwitchDropsMiner

This script allows you to AFK farm timed Twitch drops, without having to worry about switching channels when the one you were watching goes offline, or even receiving the stream data itself. This helps both you and Twitch save on bandwidth and hassle. Everybody wins!

**Features:**

- Stream-less drop mining - save on bandwidth.
- Stream options vs drop campaign options validation, so you don't end up watching a stream that can't earn you the drop.
- Stream switching when the one you were currently watching goes offline.
- Cookie saving between sessions, so you don't need to login every time.

**Not managed / TODO / manual:**

- Adding additional drop campaigns from other games to your inventory (requires you to do account [linking](https://www.twitch.tv/drops/campaigns) yourself)
- Stopping the mining if the last available drop has been mined.
- A hard limit of up to ~45 streams to manage at the same time.

**Usage:**

- Download the [lastest release](https://github.com/DevilXD/TwitchDropsMiner/releases) - it's recommended to keep it in the folder it comes with.
- Run it - it should create a `settings.json` file, where you can put in your username and channels to watch.
- Run it again - it should ask you for your Twitch username and password (if you haven't included those in the settings file), and a 2FA key if you have one setup.
- After successful login, it should start mining right away.
- Upon closing the application, cookies will be stored in the `cookies.pickle` file, from which the authorization information will be restored on each subsequent run.
- Note: Username and password are only needed for initial login, and thus can be safely removed from the settings file afterwards. Make sure to keep your cookies file safe, as the authorization information it stores can give another person access to your Twitch account.
