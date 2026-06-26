use serde::Serialize;

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SemanticNode {
    Literal {
        content: String,
    },
    CharRange {
        start: String,
        end: String,
        exclusions: Vec<String>,
    },
    ValueRange {
        alpha: Box<SemanticNode>,
        lower: Option<String>,
        upper: Option<String>,
        lower_ref: Option<Box<SemanticNode>>,
        upper_ref: Option<Box<SemanticNode>>,
        exclusions: Vec<String>,
    },
    Union {
        options: Vec<SemanticNode>,
        exclusions: Vec<String>,
    },
    Complement {
        inner: Box<SemanticNode>,
    },
    Heterogeneous {
        inner: Box<SemanticNode>,
    },
    GroupClass {
        groups: Vec<Vec<String>>,
    },
    Sequence {
        children: Vec<ChildNode>,
    },
    BackRef {
        group: usize,
    },
    CountRef {
        group: usize,
    },
    StageRef {
        stage: usize,
        path: Vec<usize>,
    },
    Anchor {
        at: String,
    },
}

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ChildNode {
    Leaf {
        content: String,
    },
    BraceGroup {
        content: String,
        semantic: SemanticNode,
        count: Option<CountSpec>,
    },
}

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum CountSpec {
    Range {
        min: usize,
        max: Option<usize>,
        group: Option<usize>,
    },
    Set {
        values: Vec<usize>,
        group: Option<usize>,
    },
    Ref {
        group: usize,
    },
}

#[derive(Serialize, Clone, Debug)]
pub struct RootNode {
    #[serde(rename = "type")]
    pub ty: &'static str,
    pub children: Vec<ChildNode>,
    pub fixed_point: bool,
}

impl RootNode {
    pub fn new(children: Vec<ChildNode>) -> Self {
        RootNode { ty: "root", children, fixed_point: false }
    }
}
