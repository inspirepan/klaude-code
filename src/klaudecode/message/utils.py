def add_cache_control(msg: object) -> object:
    """
    Add cache control to the OpenAI or Anthropic schema.
    """
    if not msg:
        return msg
    if 'content' not in msg:
        return msg
    if isinstance(msg['content'], str):
        msg['content'] = [{'type': 'text', 'text': msg['content'], 'cache_control': {'type': 'ephemeral'}}]
    elif isinstance(msg['content'], list):
        msg['content'][-1]['cache_control'] = {'type': 'ephemeral'}
    return msg


def remove_cache_control(msg: object) -> object:
    """
    Remove cache control from the OpenAI or Anthropic schema.
    """
    if not msg:
        return msg
    if 'content' not in msg:
        return msg
    if isinstance(msg['content'], str):
        return msg
    if isinstance(msg['content'], list) and 'cache_control' in msg['content'][-1]:
        msg['content'][-1].pop('cache_control')
    return msg
