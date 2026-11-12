"""Endpoints for mapping Jira project keys to GitHub repositories."""

import uuid
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select
from app.api.deps import CurrentUserDep, SessionDep
from app.models.mapping import ProjectMapping
from app.schemas.mapping import ProjectMappingCreate, ProjectMappingOut

router = APIRouter(prefix="/mappings", tags=["Project Mappings"])


@router.post(
    "",
    response_model=ProjectMappingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Jira <-> GitHub Project Mapping",
    description="Associate a Jira project key (e.g. ENG) with a GitHub repository (e.g. owner/repo).",
)
async def create_project_mapping(
    payload: ProjectMappingCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectMappingOut:
    jira_key = payload.jira_project_key.upper().strip()
    github_repo = payload.github_repo.strip()

    # Check for existing mapping
    query = select(ProjectMapping).where(
        ProjectMapping.user_id == current_user.id,
        ProjectMapping.jira_project_key == jira_key,
        ProjectMapping.github_repo == github_repo,
    )
    result = await session.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        existing.description = payload.description
        await session.commit()
        await session.refresh(existing)
        return ProjectMappingOut.model_validate(existing)

    new_mapping = ProjectMapping(
        user_id=current_user.id,
        jira_project_key=jira_key,
        github_repo=github_repo,
        description=payload.description,
    )
    session.add(new_mapping)
    await session.commit()
    await session.refresh(new_mapping)
    return ProjectMappingOut.model_validate(new_mapping)


@router.get(
    "",
    response_model=list[ProjectMappingOut],
    status_code=status.HTTP_200_OK,
    summary="List Project Mappings",
    description="Retrieve all configured Jira to GitHub repository mappings for the authenticated user.",
)
async def list_project_mappings(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[ProjectMappingOut]:
    query = select(ProjectMapping).where(ProjectMapping.user_id == current_user.id).order_by(ProjectMapping.created_at.desc())
    result = await session.execute(query)
    mappings = result.scalars().all()
    return [ProjectMappingOut.model_validate(m) for m in mappings]


@router.delete(
    "/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Project Mapping",
    description="Remove an existing Jira to GitHub repository mapping.",
)
async def delete_project_mapping(
    mapping_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    query = delete(ProjectMapping).where(
        ProjectMapping.id == mapping_id,
        ProjectMapping.user_id == current_user.id,
    )
    result = await session.execute(query)
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    await session.commit()
