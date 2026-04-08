"""Clustering API — k-means and hierarchical clustering."""
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/clustering", tags=["Clustering"])


class AutoKRequest(BaseModel):
    variables: list[str]
    max_k: int = 10


class ClusterRequest(BaseModel):
    variables: list[str]
    method: str = "kmeans"  # kmeans, hierarchical
    n_clusters: int = 3
    linkage: str = "ward"  # ward, complete, average (for hierarchical)


@router.post("/auto-k")
async def auto_detect_k(
    project_id: UUID, data: AutoKRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Find optimal k using elbow method."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    result = await asyncio.to_thread(_compute_elbow, spss_data.df, data.variables, data.max_k)
    return success_response(result)


@router.post("/run")
async def run_clustering(
    project_id: UUID, data: ClusterRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Run k-means or hierarchical clustering."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    try:
        result = await asyncio.to_thread(
            _run_cluster, spss_data.df, data.variables, data.method, data.n_clusters, data.linkage
        )
        return success_response(result)
    except Exception as e:
        return JSONResponse(status_code=500, content=error_response("CLUSTERING_FAILED", str(e)))


def _compute_elbow(df, variables: list[str], max_k: int) -> dict:
    """Compute inertia for k=2..max_k using k-means."""
    from sklearn.cluster import KMeans
    import numpy as np

    subset = df[variables].dropna()
    if len(subset) < max_k:
        return {"error": f"Not enough data ({len(subset)} rows) for max_k={max_k}"}

    inertias = []
    for k in range(2, min(max_k + 1, len(subset))):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        km.fit(subset)
        inertias.append({"k": k, "inertia": round(float(km.inertia_), 2)})

    # Suggest optimal k (biggest drop in inertia)
    suggested_k = 3
    if len(inertias) >= 3:
        drops = [inertias[i]["inertia"] - inertias[i + 1]["inertia"] for i in range(len(inertias) - 1)]
        suggested_k = inertias[drops.index(max(drops))]["k"]

    return {"inertias": inertias, "suggested_k": suggested_k, "n_rows": len(subset)}


def _run_cluster(df, variables: list[str], method: str, n_clusters: int, linkage: str) -> dict:
    """Run clustering and return assignments + centroids."""
    import numpy as np

    subset = df[variables].dropna()
    if len(subset) < n_clusters:
        raise ValueError(f"Not enough data ({len(subset)} rows) for {n_clusters} clusters")

    if method == "kmeans":
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        labels = km.fit_predict(subset)
        centroids = km.cluster_centers_.tolist()

        cluster_sizes = {}
        for label in range(n_clusters):
            cluster_sizes[f"Cluster {label + 1}"] = int((labels == label).sum())

        return {
            "method": "kmeans",
            "n_clusters": n_clusters,
            "cluster_sizes": cluster_sizes,
            "centroids": centroids,
            "variables": variables,
            "n_rows": len(subset),
            "inertia": round(float(km.inertia_), 2),
        }

    elif method == "hierarchical":
        from scipy.cluster.hierarchy import linkage as hc_linkage, fcluster, dendrogram
        Z = hc_linkage(subset, method=linkage)
        labels = fcluster(Z, t=n_clusters, criterion="maxclust")

        cluster_sizes = {}
        for label in range(1, n_clusters + 1):
            cluster_sizes[f"Cluster {label}"] = int((labels == label).sum())

        # Dendrogram data for frontend
        dendro = dendrogram(Z, no_plot=True)

        return {
            "method": "hierarchical",
            "linkage": linkage,
            "n_clusters": n_clusters,
            "cluster_sizes": cluster_sizes,
            "dendrogram": {
                "icoord": dendro["icoord"],
                "dcoord": dendro["dcoord"],
                "color_list": dendro["color_list"],
            },
            "variables": variables,
            "n_rows": len(subset),
        }

    else:
        raise ValueError(f"Unknown method: {method}")
