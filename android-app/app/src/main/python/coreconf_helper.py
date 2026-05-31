import os
import tempfile
from pycoreconf import CORECONFModel

def get_bootstrap_sid(sid_file_content: str, module_name: str) -> str:
    """
    Writes the .sid string content to a temporary file,
    loads it using pycoreconf CORECONFModel, and retrieves
    the SID of the XPath: /{module_name}:transducers/transducer
    """
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sid", delete=False) as f:
            f.write(sid_file_content)
            temp_path = f.name
            
        try:
            model = CORECONFModel(temp_path)
            xpath = f"/{module_name}:transducers/transducer"
            if xpath in model.sids:
                return str(model.sids[xpath])
            
            # Fallback search
            for k, v in model.sids.items():
                if "transducers/transducer" in k:
                    return str(v)
                    
            return "Not found"
        finally:
            try:
                os.remove(temp_path)
            except:
                pass
    except Exception as e:
        return f"Error: {str(e)}"
