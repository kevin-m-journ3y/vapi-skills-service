import logging
from functools import wraps
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)

def vapi_tool(func: Callable) -> Callable:
    """
    Decorator to handle VAPI tool request/response formatting
    """
    @wraps(func)
    async def wrapper(request: dict):
        tool_call_id = "unknown"
        try:
            # Extract tool call data from VAPI request
            if "message" in request and "toolCalls" in request["message"]:
                tool_calls = request["message"]["toolCalls"]
                if len(tool_calls) > 0:
                    tool_call = tool_calls[0]
                    tool_call_id = tool_call.get("id", "unknown")
                    
                    if "function" in tool_call and "arguments" in tool_call["function"]:
                        function_args = tool_call["function"]["arguments"]
                    else:
                        function_args = {}
                else:
                    function_args = {}
            else:
                # Fallback: try to extract directly from request
                function_args = request
            
            logger.info(f"VAPI tool call: {func.__name__}, toolCallId: {tool_call_id}, args: {function_args}")
            
            # Call the original function with extracted arguments
            result = await func(function_args)
            
            # Return VAPI-compatible response
            response = {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": result
                }]
            }
            
            logger.info(f"VAPI tool response: {func.__name__}, success: {result.get('success', True)}")
            return response
            
        except Exception as e:
            logger.error(f"VAPI tool error in {func.__name__}: {str(e)}")
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": str(e),
                        "message": f"Error in {func.__name__}: {str(e)}"
                    }
                }]
            }
    
    return wrapper  # ← THIS LINE WAS MISSING!


def extract_vapi_args(request: dict) -> tuple[str, dict]:
    """
    Extract tool call ID and arguments from VAPI request
    Returns: (tool_call_id, arguments_dict)
    """
    tool_call_id = "unknown"
    args = {}
    
    try:
        if "message" in request and "toolCalls" in request["message"]:
            tool_calls = request["message"]["toolCalls"]
            if len(tool_calls) > 0:
                tool_call = tool_calls[0]
                tool_call_id = tool_call.get("id", "unknown")
                
                if "function" in tool_call and "arguments" in tool_call["function"]:
                    args = tool_call["function"]["arguments"]
        else:
            # Fallback for direct args
            args = request
            
    except Exception as e:
        logger.error(f"Error extracting VAPI args: {e}")
    
    return tool_call_id, args