import os
from unittest.mock import MagicMock, patch

from plex_playlist_sync.cli import main


def test_cli_missing_plex_vars():
    with patch.dict(os.environ, {}, clear=True):
        code = main()
        assert code == 1


@patch("plex_playlist_sync.cli.PlexClient")
@patch("plex_playlist_sync.cli.SyncCoordinator")
def test_cli_run_once_success(mock_coord_class, mock_plex_class):
    mock_coord = MagicMock()
    mock_coord_class.return_value = mock_coord

    env = {
        "PLEX_URL": "http://localhost:32400",
        "PLEX_TOKEN": "token",
        "RUN_ONCE": "1",
    }
    with patch.dict(os.environ, env, clear=True):
        code = main()
        assert code == 0
        mock_coord.run_sync_cycle.assert_called_once()
