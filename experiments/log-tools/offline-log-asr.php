<?php
/**
 * Plugin Name: Offline Log Tencent ASR
 * Description: Signs short-lived Tencent Cloud ASR connections for the offline log editor.
 * Version: 1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

add_action('application_password_did_authenticate', function ($user) {
    $GLOBALS['offline_log_asr_app_user'] = $user->ID;
});

add_action('rest_api_init', function () {
    register_rest_route('offline-log/v1', '/asr-session', array(
        'methods' => 'POST',
        'permission_callback' => function () {
            $user_id = get_current_user_id();
            return is_ssl()
                && !empty($GLOBALS['offline_log_asr_app_user'])
                && (int) $GLOBALS['offline_log_asr_app_user'] === $user_id
                && current_user_can('edit_posts');
        },
        'callback' => 'offline_log_asr_session',
    ));
});

function offline_log_asr_session() {
    $app = defined('OFFLINE_LOG_ASR_APP_ID') ? (string) OFFLINE_LOG_ASR_APP_ID : '';
    $id = defined('OFFLINE_LOG_ASR_SECRET_ID') ? (string) OFFLINE_LOG_ASR_SECRET_ID : '';
    $key = defined('OFFLINE_LOG_ASR_SECRET_KEY') ? (string) OFFLINE_LOG_ASR_SECRET_KEY : '';
    if (!ctype_digit($app) || !ctype_alnum($id) || $key === '') {
        return new WP_Error('offline_log_asr_config', '尚未配置腾讯云语音识别。', array('status' => 503));
    }

    $now = time();
    $params = array(
        'engine_model_type' => '16k_zh',
        'expired' => $now + 60,
        'needvad' => 1,
        'nonce' => random_int(1, 2147483647),
        'secretid' => $id,
        'timestamp' => $now,
        'voice_format' => 1,
        'voice_id' => wp_generate_uuid4(),
    );
    ksort($params, SORT_STRING);
    $target = 'asr.cloud.tencent.com/asr/v2/' . $app . '?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986);
    $signature = base64_encode(hash_hmac('sha1', $target, $key, true));
    $response = new WP_REST_Response(array('url' => 'wss://' . $target . '&signature=' . rawurlencode($signature)));
    $response->header('Cache-Control', 'private, no-store');
    return $response;
}
