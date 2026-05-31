from __future__ import annotations

def select_nodes_checkbox(nodes: list[object], trusted_ids: set[str]) -> list[object] | None:
    try:
        import questionary
    except ImportError:
        return None

    choices = [
        questionary.Choice(
            title=_node_choice_title(node, trusted=node.node_id in trusted_ids),
            value=node.node_id,
            checked=node.node_id not in trusted_ids,
        )
        for node in nodes
    ]
    selected_ids = questionary.checkbox(
        "Trust which nodes?",
        choices=choices,
        instruction="Use space to toggle, enter to confirm.",
    ).ask()
    if selected_ids is None:
        return []
    selected = set(selected_ids)
    return [node for node in nodes if node.node_id in selected]


def _node_choice_title(node: object, *, trusted: bool) -> str:
    marker = "trusted" if trusted else "new"
    transport = getattr(node, "transport", "http")
    address = getattr(node, "address", None) or getattr(node, "base_url", "")
    return f"{node.name}  {transport}  {address}  {node.auth}  {marker}"
