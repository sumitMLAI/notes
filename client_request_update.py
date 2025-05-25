from pymongo import MongoClient

def update_input_fields(tenant_id, is_change, updated_fields):
    client = MongoClient("mongodb://localhost:27017/")
    db = client["RULE_ENGINE"]
    collection = db["input_request_sub_table"]

    # Fetch current document
    document = collection.find_one({"tenant_id": tenant_id})
    if not document:
        return {
            "tenant_id": tenant_id,
            "is_change": is_change,
            "status": "Tenant not found in document"
        }

    columns = document.get("input_request", {}).get("columns", [])
    
    # Check for duplicate field names
    field_names = [field.get("input_request") for field in columns]
    duplicates = [name for name in set(field_names) if field_names.count(name) > 1]
    
    if duplicates:
        return {
            "tenant_id": tenant_id,
            "status": f"Duplicate field_name(s) found: {', '.join(duplicates)}"
        }

    # If no update requested, return only active fields
    if is_change == 0:
        filtered_fields = [field for field in columns if field.get("is_active") == 1]
        return {
            "tenant_id": tenant_id,
            "input_request": {"columns": filtered_fields},
            "status": "success"
        }

    # If update requested
    if is_change == 1 and updated_fields:
        for field in columns:
            field_name = field.get("input_request")
            if field_name in updated_fields:
                new_value = updated_fields[field_name].get("is_active")
                if new_value is not None:
                    field["is_active"] = new_value

        # Save updated document
        collection.update_one(
            {"tenant_id": tenant_id},
            {"$set": {"input_request.columns": columns}}
        )

    # Return active fields after update
    filtered_fields = [field for field in columns if field.get("is_active") == 1]

    return {
        "tenant_id": tenant_id,
        "input_request": {"columns": filtered_fields},
        "status": "success"
    }
