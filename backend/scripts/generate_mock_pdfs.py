import os
from fpdf import FPDF

def create_mock_pdfs():
    output_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'mock_documents')
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. SOC 2 Type 2 PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16, style='B')
    pdf.cell(200, 10, txt="SOC 2 Type II Audit Report", ln=True, align='C')
    
    pdf.set_font("Helvetica", size=12)
    pdf.ln(10)
    pdf.cell(200, 10, txt="Company: CyberShield Inc.", ln=True)
    pdf.cell(200, 10, txt="Audit Period: Jan 1 2025 to Dec 31 2025", ln=True)
    
    pdf.ln(5)
    pdf.set_font("Helvetica", size=14, style='B')
    pdf.cell(200, 10, txt="Executive Summary", ln=True)
    
    pdf.set_font("Helvetica", size=12)
    text = "We have examined the controls of CyberShield Inc. The controls were suitably designed and operating effectively to provide reasonable assurance that the service organization's principal service commitments and system requirements were achieved based on the trust services criteria relevant to security, availability, and confidentiality.\n\nThere were no notable exceptions or deviations found during the testing period. Expiration Date: Dec 31 2026."
    pdf.multi_cell(0, 10, txt=text)
    
    pdf.output(os.path.join(output_dir, 'CyberShield_SOC2.pdf'))
    
    # 2. Bad Pen Test PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16, style='B')
    pdf.cell(200, 10, txt="Penetration Test Report - FAILED", ln=True, align='C')
    
    pdf.set_font("Helvetica", size=12)
    pdf.ln(10)
    pdf.cell(200, 10, txt="Target: PiedPiper Cloud Analytics", ln=True)
    pdf.cell(200, 10, txt="Date of test: April 1, 2026", ln=True)
    
    pdf.ln(5)
    pdf.set_font("Helvetica", size=14, style='B')
    pdf.cell(200, 10, txt="Critical Findings", ln=True)
    
    pdf.set_font("Helvetica", size=12)
    text = "- Authentication bypass discovered in /api/v1/auth/login endpoint.\n- Server Side Request Forgery (SSRF) present on the webhook handler.\n- Unencrypted passwords discovered in the logging infrastructure.\n\nRecommendation: Immediate system shutdown recommended until critical vulnerabilities are patched. Score: 2/10."
    pdf.multi_cell(0, 10, txt=text)
    
    pdf.output(os.path.join(output_dir, 'PiedPiper_Bad_PenTest.pdf'))
    
    print(f"Mock PDFs successfully generated in: {os.path.abspath(output_dir)}")

if __name__ == '__main__':
    create_mock_pdfs()
