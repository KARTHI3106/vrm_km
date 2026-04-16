import os
import re

file_path = 'd:\\vrm\\backend\\app\\api\\routes.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add get_llm
content = content.replace('from app.core.llm import check_llm_health', 'from app.core.llm import check_llm_health, get_llm')

# Add VendorExtraction
vendor_extraction = '''class VendorExtraction(BaseModel):
    vendor_name: str = Field(description="Name of the vendor being onboarded. Default to 'Unknown Vendor' if not specified.", default="Unknown Vendor")
    vendor_type: str = Field(description="Type of vendor, e.g., technology, saas, consulting.", default="technology")
    contract_value: float = Field(description="Contract value in USD. Parse as float, without symbols.", default=0.0)
    vendor_domain: str = Field(description="Domain name of the vendor (e.g., example.com).", default="")
    contact_email: str = Field(description="Contact email address.", default="")
    contact_name: str = Field(description="Name of the contact person.", default="")

'''

content = content.replace('class VendorOnboardRequest(BaseModel):', vendor_extraction + 'class VendorOnboardRequest(BaseModel):')

# Replace exact endpoint method
new_onboard = '''@router.post("/vendors/onboard")
async def onboard_vendor(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    """
    Start the vendor onboarding process.
    Accepts natural language command and document uploads, then triggers the
    multi-agent workflow in the background.
    """
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        structured_llm = llm.with_structured_output(VendorExtraction)
        extraction = structured_llm.invoke(f"Extract vendor onboarding details from the following command:\\n{prompt}")
        
        # Create vendor record
        vendor_data = {
            "name": extraction.vendor_name,
            "vendor_type": extraction.vendor_type,
            "contract_value": extraction.contract_value,
            "domain": extraction.vendor_domain,
            "contact_email": extraction.contact_email,
            "contact_name": extraction.contact_name,
            "status": "processing",
        }
        vendor = create_vendor(vendor_data)
        vendor_id = vendor.get("id")

        if not vendor_id:
            raise HTTPException(status_code=500, detail="Failed to create vendor record")

        # Save uploaded files
        settings = get_settings()
        upload_dir = os.path.join(settings.upload_dir, vendor_id)
        os.makedirs(upload_dir, exist_ok=True)

        file_paths = []
        for f in files:
            file_path = os.path.join(upload_dir, f.filename)
            content_bytes = await f.read()
            with open(file_path, "wb") as fp:
                fp.write(content_bytes)
            file_paths.append(file_path)
            logger.info(f"Saved file: {file_path}")

        # Trigger the multi-agent workflow in the background
        background_tasks.add_task(
            _run_workflow_sync,
            vendor_id=vendor_id,
            vendor_name=extraction.vendor_name,
            vendor_type=extraction.vendor_type,
            contract_value=extraction.contract_value,
            vendor_domain=extraction.vendor_domain,
            file_paths=file_paths,
        )

        return {
            "status": "accepted",
            "vendor_id": vendor_id,
            "message": f"Vendor {extraction.vendor_name} onboarding started.",
            "files_uploaded": [f.filename for f in files],
            "status_url": f"/api/v1/vendors/{vendor_id}/status",
            "report_url": f"/api/v1/vendors/{vendor_id}/report",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vendor onboarding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))'''

content = re.sub(r'@router\.post\(\"/vendors/onboard\"\).*?raise HTTPException\(status_code=500, detail=str\(e\)\)', new_onboard, content, flags=re.DOTALL)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
