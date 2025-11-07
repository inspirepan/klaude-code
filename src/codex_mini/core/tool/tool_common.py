def truncate_tool_output(output: str, max_length: int = 40000) -> str:
    if len(output) > max_length:
        truncated_output_length = len(output) - max_length
        return output[:max_length] + f"... (truncated {truncated_output_length} characters)"
    return output
