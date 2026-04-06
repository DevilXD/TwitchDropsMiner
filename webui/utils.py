from datetime import datetime


def get_campaign_status(campaign) -> str:
    if hasattr(campaign, 'active') and campaign.active:
        return "Active"
    elif hasattr(campaign, 'upcoming') and campaign.upcoming:
        return "Upcoming"
    elif hasattr(campaign, 'expired') and campaign.expired:
        return "Expired"
    else:
        return "Unknown"


def get_campaign_progress(campaign) -> float:
    if hasattr(campaign, 'drops'):
        for drop in campaign.drops:
            if hasattr(drop, 'current_minutes') and hasattr(drop, 'required_minutes'):
                if drop.required_minutes > 0:
                    return (drop.current_minutes / drop.required_minutes) * 100
    return 0.0


def format_time_remaining(campaign) -> str:
    try:
        if hasattr(campaign, 'active') and campaign.active and hasattr(campaign, 'ends_at'):
            import pytz
            now = datetime.now(pytz.UTC)
            time_diff = campaign.ends_at - now
            if time_diff.total_seconds() > 0:
                days = time_diff.days
                hours, remainder = divmod(time_diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)

                if days > 0:
                    return f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    return f"{hours}h {minutes}m"
                else:
                    return f"{minutes}m"
        elif hasattr(campaign, 'upcoming') and campaign.upcoming and hasattr(campaign, 'starts_at'):
            import pytz
            now = datetime.now(pytz.UTC)
            time_diff = campaign.starts_at - now
            if time_diff.total_seconds() > 0:
                days = time_diff.days
                hours, remainder = divmod(time_diff.seconds, 3600)
                if days > 0:
                    return f"Starts in {days}d {hours}h"
                else:
                    return f"Starts in {hours}h"
    except Exception:
        pass

    return ""


def should_show_campaign_with_filters(campaign_data: dict, filters: dict) -> bool:
    """Return True if the campaign passes the active inventory filters.

    The inventory panel uses five boolean filters (not_linked, upcoming, expired,
    excluded, finished).  When no filters are enabled nothing is shown.
    """
    campaign = campaign_data.get('campaign_obj')

    show_not_linked = filters.get("not_linked", False)
    show_upcoming   = filters.get("upcoming", False)
    show_active     = filters.get("active", False)
    show_expired    = filters.get("expired", False)
    show_excluded   = filters.get("excluded", False)
    show_finished   = filters.get("finished", False)

    status = campaign_data.get('status', '').lower()

    # Without a real campaign object (e.g. in tests), filter purely by status string.
    if not campaign:
        any_filter_enabled = (show_not_linked or show_upcoming or show_active or show_expired or
                              show_excluded or show_finished)
        if not any_filter_enabled:
            return False

        if status == 'upcoming':
            return show_upcoming
        elif status == 'active':
            return show_active
        elif status == 'expired':
            return show_expired
        elif status == 'finished':
            return show_finished
        else:
            # Unknown status — don't show.
            return False

    # "not_linked" filter hides campaigns the user isn't eligible for.
    eligible = getattr(campaign, 'eligible', True)
    if show_not_linked and not eligible:
        return False

    if status == 'upcoming':
        return show_upcoming
    elif status == 'active':
        return show_active
    elif status == 'expired':
        return show_expired
    elif status == 'finished':
        return show_finished

    return True
