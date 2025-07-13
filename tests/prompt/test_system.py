import subprocess
from unittest.mock import MagicMock, patch

from klaudecode.prompt.system import _get_git_status, get_system_prompt_dynamic_part


class TestGetGitStatus:
    def test_non_git_directory_returns_empty(self, tmp_path):
        """Test that non-git directories return empty string"""
        result = _get_git_status(tmp_path)
        assert result == ''

    def test_git_directory_with_branch_and_commits(self, tmp_path):
        """Test git status with branch info, changes and commits"""
        # Create a fake git repo
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        with patch('subprocess.run') as mock_run:
            # Mock branch detection
            def mock_subprocess_run(cmd, **kwargs):
                response = MagicMock()
                response.returncode = 0
                if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                    response.stdout = 'main\n'
                elif cmd == ['git', 'rev-parse', '--abbrev-ref', 'origin/HEAD']:
                    response.stdout = 'origin/main\n'
                elif cmd == ['git', 'status', '--porcelain']:
                    response.stdout = ' M src/file.py\nM  src/changed.py\n'
                elif cmd == ['git', 'log', '--oneline', '-5']:
                    response.stdout = 'abc1234 fix: bug in parser\ndef5678 feat: add new feature\n'
                return response

            mock_run.side_effect = mock_subprocess_run

            result = _get_git_status(tmp_path)

            assert 'gitStatus:' in result
            assert 'Current branch: main' in result
            assert 'Main branch (you will usually use this for PRs): main' in result
            # Test main functionality - presence of git info
            assert 'Status:' in result
            assert 'src/changed.py' in result  # At least one file should appear
            assert 'abc1234 fix: bug in parser' in result
            assert 'def5678 feat: add new feature' in result

    def test_git_directory_no_changes(self, tmp_path):
        """Test git status with no changes"""
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        with patch('subprocess.run') as mock_run:

            def mock_subprocess_run(cmd, **kwargs):
                response = MagicMock()
                response.returncode = 0
                if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                    response.stdout = 'develop\n'
                elif cmd == ['git', 'rev-parse', '--abbrev-ref', 'origin/HEAD']:
                    response.stdout = 'origin/main\n'
                elif cmd == ['git', 'status', '--porcelain']:
                    response.stdout = ''  # No changes
                elif cmd == ['git', 'log', '--oneline', '-5']:
                    response.stdout = '1234567 Update README\n'
                return response

            mock_run.side_effect = mock_subprocess_run

            result = _get_git_status(tmp_path)

            assert 'Current branch: develop' in result
            assert 'Main branch (you will usually use this for PRs): main' in result
            assert '(clean)' in result
            assert '1234567 Update README' in result

    def test_git_subprocess_fails_gracefully(self, tmp_path):
        """Test that function handles subprocess failures gracefully"""
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='')
            result = _get_git_status(tmp_path)
            # Should return empty string instead of crashing
            assert result == ''

    def test_exception_handling(self, tmp_path):
        """Test that exceptions are handled gracefully"""
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['git'], 10)):
            result = _get_git_status(tmp_path)
            assert result == ''


class TestSystemPromptDynamicPart:
    def test_includes_git_status_in_git_repo(self, tmp_path):
        """Test that git status is included in git repositories"""
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = get_system_prompt_dynamic_part(work_dir=tmp_path)

            # Should contain the system prompt parts
            assert 'Here is useful information about the environment' in result
            assert 'IMPORTANT: Assist with defensive security tasks' in result

    def test_excludes_git_status_in_non_git_repo(self, tmp_path):
        """Test that git status is excluded in non-git directories"""
        # Don't create .git directory

        result = get_system_prompt_dynamic_part(work_dir=tmp_path)

        # Should not contain gitStatus in non-git repo
        assert 'gitStatus:' not in result
        assert 'Here is useful information about the environment' in result
        assert 'IMPORTANT: Assist with defensive security tasks' in result
