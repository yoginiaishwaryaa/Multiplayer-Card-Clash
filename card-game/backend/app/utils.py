def log_debug(node_id: str, msg: str):
    print(f"[{node_id}] {msg}")

def is_valid_play(top_card: dict, played_card: dict) -> bool:
    """
    Valid play: played card rank is ±1 of top card rank.
    Ace (1) and King (13) wrap around each other.
    Suit does NOT affect validity.
    """
    top_rank = top_card["rank"]
    played_rank = played_card["rank"]
    diff = abs(top_rank - played_rank)
    if diff == 1:
        return True
    # Ace <-> King wrap
    if (top_rank == 1 and played_rank == 13) or (top_rank == 13 and played_rank == 1):
        return True
    return False

def card_label(card: dict) -> str:
    """Human readable label like 'A♠', 'K♥', '7♣'"""
    rank = card["rank"]
    suit = card["suit"]
    if rank == 1:
        face = "A"
    elif rank == 11:
        face = "J"
    elif rank == 12:
        face = "Q"
    elif rank == 13:
        face = "K"
    else:
        face = str(rank)
    return f"{face}{suit}"
