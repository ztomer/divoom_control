//! LAN transport body-building + response-validation parity (the ACK != success
//! honesty), mirroring divoom_lib/lan_transport.py's _validate_lan_response.

use divoomd::lan::{validate_response, LanError, LanTransport};
use serde_json::json;

#[test]
fn build_body_merges_command_token_and_extra() {
    let lan = LanTransport::new("192.168.1.42", 0);
    let body = lan.build_body("Channel/SetIndex", Some(json!({"SelectIndex": 2})));
    assert_eq!(
        body,
        json!({"Command": "Channel/SetIndex", "LocalToken": 0, "SelectIndex": 2})
    );
}

#[test]
fn base_url_is_the_local_api_endpoint() {
    let lan = LanTransport::new("10.0.0.5", 7);
    assert_eq!(lan.base_url(), "http://10.0.0.5:9000/divoom_api");
}

#[test]
fn validate_ok_on_error_code_zero() {
    let r = validate_response(200, r#"{"error_code":0,"foo":1}"#, "Channel/GetIndex");
    assert_eq!(r.unwrap(), json!({"error_code": 0, "foo": 1}));
}

#[test]
fn validate_tolerates_missing_error_code() {
    // missing error_code -> treated as success (matches Python)
    assert!(validate_response(200, r#"{"foo":1}"#, "X").is_ok());
}

#[test]
fn validate_rejects_nonzero_error_code() {
    // HTTP 200 with a non-zero error_code is a REJECTION, not a silent success.
    let err = validate_response(200, r#"{"error_code":5}"#, "Channel/SetIndex").unwrap_err();
    assert_eq!(
        err,
        LanError::Rejected {
            code: "5".into(),
            command: "Channel/SetIndex".into()
        }
    );
}

#[test]
fn validate_rejects_non_200_with_json_body() {
    let err = validate_response(500, r#"{"error_code":0}"#, "X").unwrap_err();
    assert_eq!(
        err,
        LanError::BadStatus {
            status: 500,
            command: "X".into()
        }
    );
}

#[test]
fn validate_rejects_non_json_body() {
    // JSON is parsed FIRST, so a 500 with an HTML body reports non-JSON.
    let err = validate_response(500, "<html>oops</html>", "X").unwrap_err();
    assert!(matches!(err, LanError::NonJson { .. }));
}

#[test]
fn validate_tolerates_non_object_json() {
    // a JSON array has no error_code -> success (Python: err = None for non-dict)
    assert!(validate_response(200, "[1,2,3]", "X").is_ok());
}
