from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from src.client_request_update import update_input_fields
from src.client_request_handle import DynamicInput
# Initialize FastAPI app
rule_engine = FastAPI()

# Define request model
class FieldUpdateRequest(BaseModel):
    tenant_id: str
    is_change: int
    updated_fields: Optional[Dict[str, Dict[str, int]]] = None  # nested dict: {"field": {"is_active": 1}}

@rule_engine.post("/checkout_input_request")
def check_client_request(request: FieldUpdateRequest):
    tenant_id = request.tenant_id
    is_change = request.is_change
    updated_fields = request.updated_fields or {}
    
    try:
        result = update_input_fields(tenant_id, is_change, updated_fields)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@rule_engine.post("/submit_input")
def submit_data(data: DynamicInput):
    try:
        response = handle_dynamic_input(data.root)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

