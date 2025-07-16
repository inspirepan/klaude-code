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
