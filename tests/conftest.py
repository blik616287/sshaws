"""Pytest fixtures for sshaws tests."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_boto3_session():
    """Create a mock boto3 session with SSM and EC2 clients."""
    with patch('sshaws.cli.boto3.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session.profile_name = None
        mock_session.region_name = 'us-east-1'

        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_session.client.side_effect = lambda service: {
            'ssm': mock_ssm,
            'ec2': mock_ec2
        }[service]

        mock_session_class.return_value = mock_session

        yield {
            'session_class': mock_session_class,
            'session': mock_session,
            'ssm': mock_ssm,
            'ec2': mock_ec2
        }


@pytest.fixture
def sample_ec2_instances():
    """Sample EC2 describe_instances response."""
    return {
        'Reservations': [
            {
                'Instances': [
                    {
                        'InstanceId': 'i-1234567890abcdef0',
                        'State': {'Name': 'running'},
                        'PrivateIpAddress': '10.0.1.100',
                        'PublicIpAddress': '54.1.2.3',
                        'Tags': [{'Key': 'Name', 'Value': 'web-server'}]
                    },
                    {
                        'InstanceId': 'i-0987654321fedcba0',
                        'State': {'Name': 'running'},
                        'PrivateIpAddress': '10.0.1.101',
                        'Tags': [{'Key': 'Name', 'Value': 'db-server'}]
                    },
                    {
                        'InstanceId': 'i-terminated12345678',
                        'State': {'Name': 'terminated'},
                        'Tags': [{'Key': 'Name', 'Value': 'old-server'}]
                    },
                    {
                        'InstanceId': 'i-notags1234567890',
                        'State': {'Name': 'running'},
                        'PrivateIpAddress': '10.0.1.102',
                        'Tags': []
                    }
                ]
            }
        ]
    }


@pytest.fixture
def sample_ssm_instances():
    """Sample SSM describe_instance_information response."""
    return {
        'InstanceInformationList': [
            {
                'InstanceId': 'i-1234567890abcdef0',
                'PingStatus': 'Online',
                'PlatformType': 'Linux',
                'PlatformName': 'Amazon Linux'
            },
            {
                'InstanceId': 'i-notags1234567890',
                'PingStatus': 'Offline',
                'PlatformType': 'Linux',
                'PlatformName': 'Ubuntu'
            }
        ]
    }
