import json
import urllib.request
import urllib.parse
import os

JENKINS_WEBHOOK_URL = os.environ['JENKINS_WEBHOOK_URL']
ACK_MESSAGE     = os.environ.get('ACK_MESSAGE', '⏳ On it — triggering now...')
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')


def lambda_handler(event, context):
    body = event.get('body', '')
    if event.get('isBase64Encoded') and body:
        import base64
        body = base64.b64decode(body).decode('utf-8')

    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    flat   = {k: v[0] for k, v in parsed.items()}

    # Modal submission
    if 'payload' in flat:
        payload = json.loads(flat['payload'])
        if payload.get('type') == 'view_submission':
            return handle_modal_submission(payload)
        return {'statusCode': 200, 'body': ''}

    # Slash command
    text       = flat.get('text', '').strip()
    trigger_id = flat.get('trigger_id', '')
    channel_id = flat.get('channel_id', '')
    user_id    = flat.get('user_id', '')
    user_name  = flat.get('user_name', '')
    command    = flat.get('command', '/sanity')

    if not text:
        return open_modal(trigger_id, channel_id, user_id, user_name, command)

    # Text present — existing flow unchanged
    return forward_to_jenkins(body)


SQUAD_OPTIONS = [{'text': {'type': 'plain_text', 'text': s}, 'value': s}
                 for s in ['vikings', 'avengers', 'alpha', 'mavericks']]


def open_modal(trigger_id, channel_id, user_id, user_name, command):
    modal = {
        'type': 'modal',
        'callback_id': 'jenkins_trigger',
        'private_metadata': f"{channel_id}:{user_id}:{user_name}:{command}",
        'title':  {'type': 'plain_text', 'text': 'Trigger Jenkins Run'},
        'submit': {'type': 'plain_text', 'text': 'Trigger'},
        'close':  {'type': 'plain_text', 'text': 'Cancel'},
        'blocks': [
            {
                'type': 'input', 'block_id': 'env_block',
                'label': {'type': 'plain_text', 'text': 'Environment'},
                'element': {
                    'type': 'static_select', 'action_id': 'env_select',
                    'placeholder': {'type': 'plain_text', 'text': 'Select environment'},
                    'options': [{'text': {'type': 'plain_text', 'text': e}, 'value': e}
                                for e in ['qc', 'stage', 'prod', 'master']]
                }
            },
            {
                'type': 'input', 'block_id': 'version_block',
                'label': {'type': 'plain_text', 'text': 'Version'},
                'element': {
                    'type': 'plain_text_input', 'action_id': 'version_input',
                    'placeholder': {'type': 'plain_text', 'text': 'e.g. 4.1 or 4.1-Patch'}
                }
            },
            {
                'type': 'input', 'block_id': 'squad_block',
                'label': {'type': 'plain_text', 'text': 'Squad'},
                'element': {
                    'type': 'static_select', 'action_id': 'squad_select',
                    'placeholder': {'type': 'plain_text', 'text': 'Select squad'},
                    'options': SQUAD_OPTIONS
                }
            },
            {
                'type': 'input', 'block_id': 'interface_block',
                'label': {'type': 'plain_text', 'text': 'Interface'},
                'element': {
                    'type': 'static_select', 'action_id': 'interface_select',
                    'placeholder': {'type': 'plain_text', 'text': 'Select interface'},
                    'options': [{'text': {'type': 'plain_text', 'text': i}, 'value': i}
                                for i in ['api', 'cli', 'terraform']]
                }
            },
            {
                'type': 'input', 'block_id': 'rctl_block',
                'label': {'type': 'plain_text', 'text': 'rctl Build Number'},
                'element': {
                    'type': 'plain_text_input', 'action_id': 'rctl_input',
                    'placeholder': {'type': 'plain_text', 'text': 'prod: 2 | others: use latest'}
                }
            },
            {
                'type': 'input', 'block_id': 'rctl_branch_block',
                'optional': True,
                'label': {'type': 'plain_text', 'text': 'rctl Branch Override'},
                'element': {
                    'type': 'plain_text_input', 'action_id': 'rctl_branch_input',
                    'placeholder': {'type': 'plain_text', 'text': 'e.g. r4.1.2 — prod patches only; leave blank to auto-derive'}
                }
            },
            {
                'type': 'input', 'block_id': 'tf_block',
                'optional': True,
                'label': {'type': 'plain_text', 'text': 'Terraform Version'},
                'element': {
                    'type': 'plain_text_input', 'action_id': 'tf_input',
                    'placeholder': {'type': 'plain_text', 'text': 'latest: v4.1.x:19 — only for terraform interface'}
                }
            },
            {
                'type': 'input', 'block_id': 'threads_block',
                'optional': True,
                'label': {'type': 'plain_text', 'text': 'Thread Count'},
                'element': {
                    'type': 'plain_text_input', 'action_id': 'threads_input',
                    'initial_value': '5',
                    'placeholder': {'type': 'plain_text', 'text': 'default: 5'}
                }
            },
            {
                'type': 'input', 'block_id': 'oci_block',
                'optional': True,
                'label': {'type': 'plain_text', 'text': 'OCI Docker Agent'},
                'element': {
                    'type': 'checkboxes', 'action_id': 'oci_checkbox',
                    'options': [{'text': {'type': 'plain_text', 'text': 'Enable OCI instance'}, 'value': 'true'}]
                }
            }
        ]
    }
    try:
        req = urllib.request.Request(
            'https://slack.com/api/views.open',
            data=json.dumps({'trigger_id': trigger_id, 'view': modal}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {SLACK_BOT_TOKEN}'},
            method='POST'
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=2).read())
        if not resp.get('ok'):
            print(f"views.open failed: {resp.get('error')}")
    except Exception as e:
        print(f"views.open error: {e}")
    return {'statusCode': 200, 'body': ''}


def handle_modal_submission(payload):
    values = payload['view']['state']['values']
    meta   = payload['view']['private_metadata'].split(':')
    channel_id = meta[0]
    user_id    = meta[1]
    user_name  = meta[2]
    command    = meta[3] if len(meta) > 3 else '/sanity'

    env       = values['env_block']['env_select']['selected_option']['value']
    version   = values['version_block']['version_input']['value'].strip()
    squad     = values['squad_block']['squad_select']['selected_option']['value']
    interface = values['interface_block']['interface_select']['selected_option']['value']
    rctl         = (values['rctl_block']['rctl_input'].get('value') or '').strip()
    rctl_branch  = (values['rctl_branch_block']['rctl_branch_input'].get('value') or '').strip()
    tf           = (values['tf_block']['tf_input'].get('value') or '').strip()
    threads = (values['threads_block']['threads_input'].get('value') or '').strip()
    oci     = 'true' if values['oci_block']['oci_checkbox'].get('selected_options') else 'false'

    parts = [env, version]
    if rctl:
        parts.append(rctl)
    parts += [squad, interface]
    if interface == 'terraform' and tf:
        parts.append(tf)
    if threads:
        parts.append(threads)

    synthetic = urllib.parse.urlencode({
        'command': command, 'text': ' '.join(parts),
        'user_id': user_id, 'user_name': user_name,
        'channel_id': channel_id, 'channel_name': '',
        'oci': oci,
        'rctl_branch_override': rctl_branch,
    })
    forward_to_jenkins(synthetic)
    return {'statusCode': 200, 'body': ''}


def forward_to_jenkins(body):
    try:
        req = urllib.request.Request(
            JENKINS_WEBHOOK_URL,
            data=body.encode('utf-8') if isinstance(body, str) else body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Jenkins forward error: {e}")
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'response_type': 'ephemeral', 'text': ACK_MESSAGE})
    }
