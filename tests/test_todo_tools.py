"""Tests for todo-related tools."""

import pytest

from klaude_code.core.tool.todo.todo_write_tool import get_new_completed_todos
from klaude_code.core.tool.todo.update_plan_tool import PlanItemArguments, UpdatePlanArguments
from klaude_code.protocol.model import TodoItem


class TestGetNewCompletedTodos:
    """Test get_new_completed_todos function."""

    def test_no_todos(self):
        """Test with empty todo lists."""
        result = get_new_completed_todos([], [])
        assert result == []

    def test_new_completed_todo(self):
        """Test detecting newly completed todo."""
        old_todos = [
            TodoItem(content="Task 1", status="pending"),
            TodoItem(content="Task 2", status="in_progress"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="completed"),
            TodoItem(content="Task 2", status="in_progress"),
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert result == ["Task 1"]

    def test_multiple_newly_completed(self):
        """Test detecting multiple newly completed todos."""
        old_todos = [
            TodoItem(content="Task 1", status="pending"),
            TodoItem(content="Task 2", status="pending"),
            TodoItem(content="Task 3", status="pending"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="completed"),
            TodoItem(content="Task 2", status="completed"),
            TodoItem(content="Task 3", status="pending"),
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert set(result) == {"Task 1", "Task 2"}

    def test_already_completed_not_counted(self):
        """Test that already completed todos are not counted again."""
        old_todos = [
            TodoItem(content="Task 1", status="completed"),
            TodoItem(content="Task 2", status="pending"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="completed"),
            TodoItem(content="Task 2", status="completed"),
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert result == ["Task 2"]

    def test_brand_new_completed_todo(self):
        """Test brand new todo that starts as completed."""
        old_todos = [
            TodoItem(content="Task 1", status="pending"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="pending"),
            TodoItem(content="Task 2", status="completed"),  # New and completed
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert result == ["Task 2"]

    def test_status_changed_to_non_completed(self):
        """Test status change to non-completed is not counted."""
        old_todos = [
            TodoItem(content="Task 1", status="pending"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="in_progress"),
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert result == []

    def test_completed_reverted_to_pending(self):
        """Test completed todo reverted to pending is not counted."""
        old_todos = [
            TodoItem(content="Task 1", status="completed"),
        ]
        new_todos = [
            TodoItem(content="Task 1", status="pending"),
        ]
        result = get_new_completed_todos(old_todos, new_todos)
        assert result == []


class TestPlanItemArguments:
    """Test PlanItemArguments validation."""

    def test_valid_plan_item(self):
        """Test valid plan item creation."""
        item = PlanItemArguments(step="Do something", status="pending")
        assert item.step == "Do something"
        assert item.status == "pending"

    def test_all_status_types(self):
        """Test all valid status types."""
        from klaude_code.protocol.model import TodoStatusType

        statuses: list[TodoStatusType] = ["pending", "in_progress", "completed"]
        for status in statuses:
            item = PlanItemArguments(step="Task", status=status)
            assert item.status == status

    def test_empty_step_fails(self):
        """Test that empty step fails validation."""
        with pytest.raises(ValueError) as exc_info:
            PlanItemArguments(step="", status="pending")
        assert "non-empty string" in str(exc_info.value)

    def test_whitespace_only_step_fails(self):
        """Test that whitespace-only step fails validation."""
        with pytest.raises(ValueError) as exc_info:
            PlanItemArguments(step="   ", status="pending")
        assert "non-empty string" in str(exc_info.value)


class TestUpdatePlanArguments:
    """Test UpdatePlanArguments validation."""

    def test_valid_plan(self):
        """Test valid plan creation."""
        args = UpdatePlanArguments(
            plan=[
                PlanItemArguments(step="Step 1", status="completed"),
                PlanItemArguments(step="Step 2", status="in_progress"),
                PlanItemArguments(step="Step 3", status="pending"),
            ]
        )
        assert len(args.plan) == 3
        assert args.explanation is None

    def test_plan_with_explanation(self):
        """Test plan with optional explanation."""
        args = UpdatePlanArguments(
            plan=[PlanItemArguments(step="Step 1", status="pending")],
            explanation="Starting work on feature",
        )
        assert args.explanation == "Starting work on feature"

    def test_empty_plan_fails(self):
        """Test that empty plan fails validation."""
        with pytest.raises(ValueError) as exc_info:
            UpdatePlanArguments(plan=[])
        assert "at least one item" in str(exc_info.value)

    def test_multiple_in_progress_fails(self):
        """Test that multiple in_progress items fail validation."""
        with pytest.raises(ValueError) as exc_info:
            UpdatePlanArguments(
                plan=[
                    PlanItemArguments(step="Step 1", status="in_progress"),
                    PlanItemArguments(step="Step 2", status="in_progress"),
                ]
            )
        assert "at most one in_progress" in str(exc_info.value)

    def test_single_in_progress_allowed(self):
        """Test that single in_progress is allowed."""
        args = UpdatePlanArguments(
            plan=[
                PlanItemArguments(step="Step 1", status="completed"),
                PlanItemArguments(step="Step 2", status="in_progress"),
                PlanItemArguments(step="Step 3", status="pending"),
            ]
        )
        assert len([p for p in args.plan if p.status == "in_progress"]) == 1

    def test_no_in_progress_allowed(self):
        """Test that no in_progress items is allowed."""
        args = UpdatePlanArguments(
            plan=[
                PlanItemArguments(step="Step 1", status="completed"),
                PlanItemArguments(step="Step 2", status="pending"),
            ]
        )
        assert len([p for p in args.plan if p.status == "in_progress"]) == 0
