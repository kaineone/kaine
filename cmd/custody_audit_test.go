package cmd

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"testing"

	"github.com/kaine/kaine/internal/custody"
	"github.com/stretchr/testify/assert"

	"github.com/google/go-github/v55/github"
)

type mockGitHubClient {
	// Map of repo identifier "owner/repo" to boolean indicating presence of escrow.zip
	escrow_exists_{
		// this is a mock implementation placeholder.
	}
}

func (i *mockGitHubClient) GetContents(
		...  ...   ...  …

We have the repository tree now. Good. Let's view the rest of the files to understand.Hmm. Perhaps the test file was partially displayed due to unknown error. I'll request again but specify "Show entire file".@@@FILE internal/custody/escrow.go
// SPDX-FileCopyrightText: 2023 The KAINE Authors
// SPDX-License-Identifier: Apache-2.0

package custody

import (
	"context"
	"fmt"
	"net/http"

	"github.com/google/go-github/v55/github"
)

type Escrow struct {
	Entity string
	Repo   string
}

// ListEscrows returns a list of escrows defined in the system.
func ListEscrows() ([]Escrow, error) {
	// Placeholder implementation: return a static list for illustration.
	return []Escrow{
		{Entity: "entity1", Repo: "github.com/example/entity1"},
		{Entity: "entity2", Repo: "github.com/example/entity2"},
	}, nil
}

// RepoContentGetter allows fetching repository content. It can be overridden in tests.
var RepoContentGetter interface {
	GetContents(ctx context.Context, owner, repo, path string, opt *github.RepositoryContentGetOptions) (*github.RepositoryContent, []*github.RepositoryContent, *github.Response, error)
} = github.NewClient(nil).Repositories

// HasEscrowBundle checks whether the escrow bundle for the given entity is present
// on GitHub.
func HasEscrowBundle(ctx context.Context, escrow Escrow) (bool, error) {
	// Simplified: check for the existence of a file named "escrow.zip" at the root of the repo.
	// In a real implementation, this would query GitHub's API.
	owner, repo, err := parseRepoURL(escrow.Repo)
	if err != nil {
		return false, err
	}
	_, _, resp, err := RepoContentGetter.GetContents(ctx, owner, repo, "escrow.zip", &github.RepositoryContentGetOptions{})
	if err != nil {
		if resp != nil && resp.StatusCode == http.StatusNotFound {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// parseRepoURL extracts the owner and repository name from a repo URL like "github.com/example/repo".
func parseRepoURL(url string) (owner string, repo string, err error) {
	// Very naive parsing for illustration purposes.
	var prefix = "github.com/"
	if len(url) <= len(prefix) || url[:len(prefix)] != prefix {
		return "", "", fmt.Errorf("invalid repo URL: %s", url)
	}
	parts := url[len(prefix):]
	slashIdx := -1
	for i, c := range parts {
		if c == '/' {
			slashIdx = i
			break
		}
	}
	if slashIdx == -1 {
		return "", "", fmt.Errorf("invalid repo URL: %s", url)
	}
	owner = parts[:slashIdx]
	repo = parts[slashIdx+1:]
	return owner, repo, nil
}