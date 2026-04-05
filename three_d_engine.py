"""
3D Object Generation Engine — Text-to-3D via OpenAI Shap-E

Generates 3D meshes from text prompts locally using OpenAI's Shap-E model.
Exports as .glb (GL Transmission Format Binary) for Three.js rendering.

Runs 100% locally on Apple Silicon via PyTorch MPS.
Model size: ~1GB (auto-downloads on first use from HuggingFace).
"""

import os
import torch
import trimesh
import tempfile
import logging

logger = logging.getLogger("3d_engine")

# Lazy-load singleton
_models = None

def _get_models():
    """Lazy-load Shap-E models. First call downloads ~1GB from HuggingFace."""
    global _models
    if _models is None:
        from shap_e.diffusion.sample import sample_latents
        from shap_e.diffusion.gaussian_diffusion import diffusion_from_config
        from shap_e.models.download import load_model, load_config
        
        device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
        logger.info(f"[3D] Loading Shap-E models on {device}...")
        
        xm = load_model('transmitter', device=device)
        model = load_model('text300M', device=device)
        diffusion = diffusion_from_config(load_config('diffusion'))
        
        _models = {
            "xm": xm,
            "model": model,
            "diffusion": diffusion,
            "device": device,
        }
        logger.info("[3D] Shap-E models loaded successfully")
    return _models


def generate_3d_from_text(prompt: str, output_path: str, guidance_scale: float = 15.0,
                          steps: int = 64, batch_size: int = 1) -> dict:
    """
    Generate a 3D mesh from a text description.
    
    Args:
        prompt: Text description of the 3D object (e.g., "a crystal skull")
        output_path: Where to save the .glb file
        guidance_scale: How closely to follow the prompt (higher = more literal)
        steps: Diffusion steps (more = better quality, slower)
        batch_size: Number of variants to generate (1 is fastest)
    
    Returns:
        dict with status, file path, and metadata
    """
    from shap_e.diffusion.sample import sample_latents
    from shap_e.util.notebooks import decode_latent_mesh
    from security import validate_workspace_path
    
    # Validate output path stays within user directory
    if output_path:
        resolved = os.path.realpath(output_path)
        if not resolved.startswith(os.path.expanduser("~")):
            return {"status": "error", "message": "Security Error: output_path must be under user directory."}
    
    models = _get_models()
    
    logger.info(f"[3D] Generating mesh for: '{prompt}' (steps={steps}, guidance={guidance_scale})")
    
    # Generate latent representations
    latents = sample_latents(
        batch_size=batch_size,
        model=models["model"],
        diffusion=models["diffusion"],
        guidance_scale=guidance_scale,
        model_kwargs=dict(texts=[prompt] * batch_size),
        progress=True,
        clip_denoised=True,
        use_fp16=True,
        use_karras=True,
        karras_steps=steps,
        sigma_min=1e-3,
        sigma_max=160,
        s_churn=0,
    )
    
    # Decode the best latent into a mesh
    mesh = decode_latent_mesh(models["xm"], latents[0]).tri_mesh()
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    # Ensure .glb extension
    if not output_path.endswith('.glb'):
        output_path += '.glb'
    
    # Convert to trimesh and export as GLB
    vertices = mesh.verts
    faces = mesh.faces
    vertex_colors = None
    if hasattr(mesh, 'vertex_channels') and 'R' in mesh.vertex_channels:
        import numpy as np
        r = (np.array(mesh.vertex_channels['R']) * 255).astype(np.uint8)
        g = (np.array(mesh.vertex_channels['G']) * 255).astype(np.uint8)
        b = (np.array(mesh.vertex_channels['B']) * 255).astype(np.uint8)
        a = np.full_like(r, 255)
        vertex_colors = np.stack([r, g, b, a], axis=-1)
    
    tri_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, vertex_colors=vertex_colors)
    tri_mesh.export(output_path, file_type='glb')
    
    file_size = os.path.getsize(output_path)
    logger.info(f"[3D] Saved {output_path} ({file_size / 1024:.1f} KB, {len(faces)} faces)")
    
    return {
        "status": "success",
        "path": output_path,
        "prompt": prompt,
        "faces": len(faces),
        "vertices": len(vertices),
        "file_size_kb": round(file_size / 1024, 1),
    }


def generate_3d_from_image(image_path: str, output_path: str, guidance_scale: float = 3.0,
                            steps: int = 64) -> dict:
    """
    Generate a 3D mesh from an image (e.g., NFT PFP → 3D model).
    Uses Shap-E's image-conditioned model.
    
    Args:
        image_path: Path to the source image
        output_path: Where to save the .glb file
    """
    from shap_e.diffusion.sample import sample_latents
    from shap_e.util.notebooks import decode_latent_mesh
    from shap_e.models.download import load_model
    from PIL import Image
    
    models = _get_models()
    device = models["device"]
    
    # Load image-conditioned model (different from text model)
    image_model = load_model('image300M', device=device)
    
    # Load and preprocess image
    img = Image.open(image_path).convert("RGB").resize((256, 256))
    
    latents = sample_latents(
        batch_size=1,
        model=image_model,
        diffusion=models["diffusion"],
        guidance_scale=guidance_scale,
        model_kwargs=dict(images=[img]),
        progress=True,
        clip_denoised=True,
        use_fp16=True,
        use_karras=True,
        karras_steps=steps,
    )
    
    mesh = decode_latent_mesh(models["xm"], latents[0]).tri_mesh()
    
    if not output_path.endswith('.glb'):
        output_path += '.glb'
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    vertices = mesh.verts
    faces = mesh.faces
    tri_mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    tri_mesh.export(output_path, file_type='glb')
    
    file_size = os.path.getsize(output_path)
    return {
        "status": "success",
        "path": output_path,
        "source_image": image_path,
        "faces": len(faces),
        "vertices": len(vertices),
        "file_size_kb": round(file_size / 1024, 1),
    }
