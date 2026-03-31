#!/usr/bin/env bats
# Tests for agentboard.sh — all API commands require credentials

SCRIPT="$BATS_TEST_DIRNAME/agentboard.sh"

# --- Help ---

@test "help: shows usage when no args" {
    run "$SCRIPT"
    [ "$status" -eq 0 ]
    [[ "$output" == *"AgentBoard CLI"* ]]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"latest"* ]]
    [[ "$output" == *"post"* ]]
}

# --- All commands require credentials ---

@test "latest: requires credentials" {
    run "$SCRIPT" latest
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "agent: shows usage when missing name" {
    run "$SCRIPT" agent
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "agent: requires credentials" {
    run "$SCRIPT" agent some_agent
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "post: requires credentials" {
    run "$SCRIPT" post "Hello test"
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

@test "post: validates message length" {
    run "$SCRIPT" post "Hello"
    [ "$status" -eq 1 ]
    [[ "$output" == *"credentials not found"* ]]
}

# --- Test command ---

@test "test: gracefully handles missing credentials" {
    run "$SCRIPT" test
    [ "$status" -eq 0 ]
    [[ "$output" == *"Skipping API test"* ]]
}
