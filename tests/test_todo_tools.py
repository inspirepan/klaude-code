"""Tests for todo-related tools."""

from klaude_code.protocol.models import TodoItem
from klaude_code.tool.todo.todo_write_tool import TodoWriteArguments, get_new_completed_todos


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


class TestTodoWriteArguments:
    """Test TodoWriteArguments validation."""

    def test_valid_todos(self):
        """Test valid todos creation."""
        args = TodoWriteArguments(
            todos=[
                TodoItem(content="Task 1", status="completed"),
                TodoItem(content="Task 2", status="in_progress"),
                TodoItem(content="Task 3", status="pending"),
            ]
        )
        assert len(args.todos) == 3
